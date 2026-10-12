import os
from tortoise import Model, fields


class Order(Model):
    id = fields.IntField(primary_key=True)
    customer = fields.CharField(max_length=80)
    amount = fields.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        table = "orders"
        schema = os.getenv("GAUSS_SCHEMA", "gaussdb_demo")
