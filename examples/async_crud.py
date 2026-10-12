"""Run in a dedicated demo schema: python -m examples.async_crud."""

import asyncio
from decimal import Decimal
from tortoise import Tortoise
from tortoise.transactions import in_transaction
from examples.config import CONFIG
from examples.models import Order


async def main():
    await Tortoise.init(config=CONFIG)
    try:
        # Demo only. For production initialize with versioned migrations.
        await Tortoise.generate_schemas(safe=True)
        async with in_transaction():
            order = await Order.create(customer="演示客户", amount=Decimal("12.34"))
        stored = await Order.get(id=order.id)
        print(
            {"id": stored.id, "customer": stored.customer, "amount": str(stored.amount)}
        )
        await stored.delete()
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
