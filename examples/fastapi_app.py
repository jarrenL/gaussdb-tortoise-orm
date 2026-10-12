"""Run: uvicorn examples.fastapi_app:app (migrate the schema first)."""

from contextlib import asynccontextmanager
from decimal import Decimal
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from tortoise import Tortoise
from examples.models import Order


class OrderInput(BaseModel):
    customer: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(max_digits=18, decimal_places=2)


def create_app(config=None):
    @asynccontextmanager
    async def lifespan(app):
        if config is None:
            from examples.config import make_config

            effective = make_config()
        else:
            effective = config
        await Tortoise.init(config=effective)
        try:
            if os.getenv("GAUSS_DEMO_CREATE_SCHEMA") == "1":
                await Tortoise.generate_schemas(safe=True)
            yield
        finally:
            await Tortoise.close_connections()

    app = FastAPI(lifespan=lifespan)

    @app.post("/orders", status_code=201)
    async def create_order(value: OrderInput):
        order = await Order.create(**value.model_dump())
        return {"id": order.id, "customer": order.customer, "amount": str(order.amount)}

    @app.get("/orders/{order_id}")
    async def get_order(order_id: int):
        order = await Order.get_or_none(id=order_id)
        if order is None:
            raise HTTPException(404, "Order not found")
        return {"id": order.id, "customer": order.customer, "amount": str(order.amount)}

    return app


app = create_app()
