from .services import purge_expired_account_requests


class PendingAccountExpiryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        purge_expired_account_requests()
        return self.get_response(request)
