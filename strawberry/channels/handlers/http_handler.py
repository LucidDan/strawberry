"""GraphQLHTTPHandler

A consumer to provide a graphql endpoint, and optionally graphiql.
"""
import json
from pathlib import Path
from functools import cached_property
from typing import Any, Optional

from channels.generic.http import AsyncHttpConsumer
from strawberry.exceptions import MissingQueryError
from strawberry.http import (
    GraphQLHTTPResponse,
    GraphQLRequestData,
    parse_request_data,
    process_result,
)
from strawberry.schema import BaseSchema
from strawberry.types import ExecutionResult


class GraphQLHTTPConsumer(AsyncHttpConsumer):
    """A consumer to provide a view for GraphQL over HTTP.

    To use this, place it in your ProtocolTypeRouter for your channels project:

    ```
    from strawberry.channels import GraphQLHttpRouter
    from channels.routing import ProtocolTypeRouter
    from django.core.asgi import get_asgi_application
    application = ProtocolTypeRouter({
      "http": URLRouter([
        re_path("^graphql", GraphQLHTTPRouter(schema=schema)),
        re_path("^", get_asgi_application()),
      "websocket": URLRouter([
        re_path("^ws/graphql", GraphQLWebSocketRouter(schema=schema))
      ]),
    })
    """

    def __init__(
        self,
        schema: BaseSchema,
        graphiql: bool = True,
    ):
        self.schema = schema
        self.graphiql = graphiql
        super().__init__()

    @cached_property
    def headers(self):
        return {
            header_name.decode("utf-8").lower(): header_value.decode("utf-8")
            for header_name, header_value in self.scope["headers"]
        }

    async def parse_multipart_body(self, body):
        await self.send_response(500, "Unable to parse the multipart body")
        return None

    async def get_request_data(self, body) -> Optional[GraphQLRequestData]:
        if self.headers.get("content-type", "").startswith("multipart/form-data"):
            data = await self.parse_multipart_body(body)
            if data is None:
                return None
        else:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                await self.send_response(500, b"Unable to parse request body as JSON")
                return None
        try:
            return parse_request_data(data)
        except MissingQueryError:
            await self.send_response(500, b"No GraphQL query found in the request")
            return None

    async def post(self, body):
        request_data = await self.get_request_data(body)
        if request_data is None:
            return
        context = await self.get_context()
        root_value = await self.get_root_value()

        result = await self.schema.execute(
            query=request_data.query,
            root_value=root_value,
            variable_values=request_data.variables,
            context_value=context,
            operation_name=request_data.operation_name,
        )

        response_data = await self.process_result(result)
        await self.send_response(
            200,
            json.dumps(response_data).encode("utf-8"),
            headers=[(b"Content-Type", b"application/json")],
        )

    @cached_property
    def graphiql_html_file_path(self) -> Path:
        return Path(__file__).parent.parent.parent / "static" / "graphiql.html"

    async def render_graphiql(self, body):
        html_string = self.graphiql_html_file_path.read_text()
        html_string = html_string.replace("{{ SUBSCRIPTION_ENABLED }}", "true")
        await self.send_response(
            200, html_string.encode("utf-8"), headers=[(b"Content-Type", b"text/html")]
        )

    def should_render_graphiql(self):
        return bool(self.graphiql and "text/html" in self.headers.get("accept", ""))

    async def get(self, body):

        if self.should_render_graphiql():
            return await self.render_graphiql(body)

    async def handle(self, body):
        if self.scope["method"] == "GET":
            return await self.get(body)
        if self.scope["method"] == "POST":
            return await self.post(body)
        await self.send_response(
            405, b"Method not allowed", headers=[b"Allow", b"GET, POST"]
        )

    async def get_root_value(self) -> Any:
        return None

    async def get_context(self) -> Any:
        # TODO: Add context
        return None

    async def process_result(self, result: ExecutionResult) -> GraphQLHTTPResponse:
        return process_result(result)
