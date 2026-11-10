from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsClient, IsWorker
from ledger.services import get_client_wallet
from .models import Job, Bid
from .serializers import (
    JobSerializer, JobCreateSerializer, BidReadSerializer,
    BidCreateSerializer, BidFeedSerializer, JobFeedRowSerializer,
)
from .services import (
    post_job, place_bid, accept_bid, deliver, approve,
    request_revision, cancel_job, JobStateError,
)
from .scoring import top_bids_for_job


# ------------------------------------------------------------------ #
# Helper — uniform error mapping                                     #
# ------------------------------------------------------------------ #

def _service_error(exc):
    """Convert a service-layer ValidationError/JobStateError to a DRF 400."""
    msgs = getattr(exc, "messages", None) or [str(exc)]
    return Response({"error": msgs}, status=status.HTTP_400_BAD_REQUEST)


def _get_job_or_404(pk):
    try:
        return Job.objects.get(pk=pk)
    except Job.DoesNotExist:
        return None


# ------------------------------------------------------------------ #
# POST /api/jobs/              (client)  create job                   #
# GET  /api/jobs/feed/         (worker)  all biddable jobs            #
# GET  /api/jobs/my/           (any)     my jobs (role-dependent)     #
# ------------------------------------------------------------------ #

class JobCreateView(APIView):
    permission_classes = [IsClient]

    def post(self, request):
        ser = JobCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Wallet check — client must be able to fund the top of the budget
        wallet = get_client_wallet(request.user)
        if wallet.available_balance < data["budget_max"]:
            return Response(
                {"error": ["Insufficient wallet balance to post this job"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            job = post_job(
                request.user,
                title=data["title"],
                description=data["description"],
                deadline=data["deadline"],
                budget_min=data["budget_min"],
                budget_max=data["budget_max"],
                min_level=data["min_level"],
                required_skill_ids=data.get("required_skill_ids") or None,
                bid_window_hours=data["bid_window_hours"],
                max_bids=data["max_bids"],
            )
        except DjangoValidationError as e:
            return _service_error(e)

        return Response(JobSerializer(job).data, status=status.HTTP_201_CREATED)


class JobFeedView(APIView):
    """Return ALL biddable jobs, annotated for the UI's lock badge."""
    permission_classes = [IsWorker]

    def get(self, request):
        worker = request.user
        wprofile = worker.worker_profile

        # Fetch all currently-biddable jobs (still open + window not ended)
        from django.utils import timezone
        jobs = (
            Job.objects.filter(status=Job.Status.OPEN,
                               bid_window_ends_at__gt=timezone.now())
            .prefetch_related("required_skills")
            .order_by("-created_at")
        )

        my_skill_ids = set(wprofile.skills.values_list("id", flat=True))
        my_bid_job_ids = set(
            Bid.objects.filter(worker=worker).values_list("job_id", flat=True)
        )

        rows = []
        for job in jobs:
            req_ids = {s.id for s in job.required_skills.all()}
            level_ok = wprofile.level >= job.min_level
            skills_ok = req_ids.issubset(my_skill_ids) if req_ids else True

            locked = not (level_ok and skills_ok)
            if not level_ok:
                lock_reason = "level"
            elif not skills_ok:
                lock_reason = "skills"
            else:
                lock_reason = None

            already_bid = job.id in my_bid_job_ids
            can_bid = (not locked) and (not already_bid) and job.is_biddable()

            row = JobSerializer(job).data
            row.update({
                "locked": locked,
                "lock_reason": lock_reason,
                "already_bid": already_bid,
                "can_bid": can_bid,
            })
            rows.append(row)

        return Response({"count": len(rows), "results": rows})


class MyJobsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role == "client":
            qs = Job.objects.filter(client=user).prefetch_related("required_skills")
        elif user.role == "worker":
            job_ids = Bid.objects.filter(worker=user).values_list("job_id", flat=True)
            qs = Job.objects.filter(id__in=job_ids).prefetch_related("required_skills")
        else:
            return Response({"results": []})
        return Response({
            "count": qs.count(),
            "results": JobSerializer(qs.order_by("-created_at"), many=True).data,
        })


# ------------------------------------------------------------------ #
# GET  /api/jobs/{id}/         detail (role-aware)                    #
# ------------------------------------------------------------------ #

class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        job = _get_job_or_404(pk)
        if not job:
            return Response({"error": ["Not found"]}, status=404)

        data = JobSerializer(job).data
        user = request.user

        if user.id == job.client_id:
            # Owner: full bid list (sorted by score)
            data["bids"] = BidReadSerializer(
                job.bids.all().order_by("-score_total"),
                many=True,
            ).data
        elif user.role == "worker":
            own = job.bids.filter(worker=user).first()
            data["my_bid"] = BidReadSerializer(own).data if own else None

        return Response(data)


# ------------------------------------------------------------------ #
# POST /api/jobs/{id}/bids/     (worker)  place bid                   #
# ------------------------------------------------------------------ #

class BidCreateView(APIView):
    permission_classes = [IsWorker]

    def post(self, request, pk):
        job = _get_job_or_404(pk)
        if not job:
            return Response({"error": ["Not found"]}, status=404)
        ser = BidCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from fraud.services import check_rate_limit
        allowed, retry_after = check_rate_limit("bid", request.user.id)
        if not allowed:
            return Response(
                {"error": [f"Slow down. Try again in {retry_after}s."]},
                status=429,
            )
        try:
            bid = place_bid(
                request.user, job.id,
                price=ser.validated_data["price"],
                delivery_days=ser.validated_data["delivery_days"],
                message=ser.validated_data.get("message", ""),
            )
        except DjangoValidationError as e:
            return _service_error(e)
        return Response(BidReadSerializer(bid).data, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ #
# GET  /api/jobs/{id}/top-bids/     (client owner) top-3 + recommended#
# ------------------------------------------------------------------ #

class TopBidsView(APIView):
    permission_classes = [IsClient]

    def get(self, request, pk):
        job = _get_job_or_404(pk)
        if not job:
            return Response({"error": ["Not found"]}, status=404)
        if job.client_id != request.user.id:
            return Response({"error": ["Not your job"]}, status=403)

        top, recommended = top_bids_for_job(job)
        return Response({
            "top": BidFeedSerializer(top, many=True).data,
            "recommended": BidFeedSerializer(recommended).data if recommended else None,
        })


# ------------------------------------------------------------------ #
# POST /api/jobs/{id}/accept/{bid_id}/   (client)                     #
# ------------------------------------------------------------------ #

class AcceptBidView(APIView):
    permission_classes = [IsClient]

    def post(self, request, pk, bid_id):
        try:
            job, bid = accept_bid(request.user, pk, bid_id)
        except Job.DoesNotExist:
            return Response({"error": ["Job not found"]}, status=404)
        except Bid.DoesNotExist:
            return Response({"error": ["Bid not found"]}, status=404)
        except DjangoValidationError as e:
            return _service_error(e)
        return Response(JobSerializer(job).data)


# ------------------------------------------------------------------ #
# POST /api/jobs/{id}/deliver/    (worker)                            #
# ------------------------------------------------------------------ #

class DeliverView(APIView):
    permission_classes = [IsWorker]

    def post(self, request, pk):
        try:
            job = deliver(
                pk, request.user,
                delivery_text=request.data.get("delivery_text", ""),
                delivery_file_url=request.data.get("delivery_file_url", ""),
            )
        except Job.DoesNotExist:
            return Response({"error": ["Job not found"]}, status=404)
        except DjangoValidationError as e:
            return _service_error(e)
        return Response(JobSerializer(job).data)


# ------------------------------------------------------------------ #
# POST /api/jobs/{id}/approve/    (client)                            #
# POST /api/jobs/{id}/revise/     (client)                            #
# POST /api/jobs/{id}/cancel/     (client)                            #
# ------------------------------------------------------------------ #

class ApproveView(APIView):
    permission_classes = [IsClient]

    def post(self, request, pk):
        try:
            job = approve(pk, request.user)
        except Job.DoesNotExist:
            return Response({"error": ["Job not found"]}, status=404)
        except DjangoValidationError as e:
            return _service_error(e)
        return Response(JobSerializer(job).data)


class ReviseView(APIView):
    permission_classes = [IsClient]

    def post(self, request, pk):
        try:
            job = request_revision(
                pk, request.user,
                feedback=request.data.get("feedback", ""),
            )
        except Job.DoesNotExist:
            return Response({"error": ["Job not found"]}, status=404)
        except DjangoValidationError as e:
            return _service_error(e)
        return Response(JobSerializer(job).data)


class CancelView(APIView):
    permission_classes = [IsClient]

    def post(self, request, pk):
        try:
            job = cancel_job(pk, request.user)
        except Job.DoesNotExist:
            return Response({"error": ["Job not found"]}, status=404)
        except DjangoValidationError as e:
            return _service_error(e)
        return Response(JobSerializer(job).data)