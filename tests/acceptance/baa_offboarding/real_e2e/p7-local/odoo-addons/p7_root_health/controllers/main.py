from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.http import request


class P7RootHealthHome(Home):
    @http.route(
        "/",
        type="http",
        auth="none",
        methods=["GET"],
        save_session=False,
        readonly=True,
    )
    def index(self, s_action=None, db=None, **kwargs):
        return request.make_response(
            "p7-local-odoo-root-ready\n",
            headers=[
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Cache-Control", "no-store"),
            ],
            status=200,
        )
