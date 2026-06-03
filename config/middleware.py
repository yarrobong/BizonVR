from .utils.marketing import persist_marketing_context


class MarketingContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        persist_marketing_context(request)
        return self.get_response(request)
