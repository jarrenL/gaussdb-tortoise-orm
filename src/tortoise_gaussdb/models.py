"""Optional model base correcting Tortoise 1.1.8 source-field refresh."""

from tortoise import Model
from tortoise.exceptions import OperationalError


class GaussDBModel(Model):
    """Use logical model attributes when refreshing physical source columns."""

    class Meta:
        abstract = True

    async def refresh_from_db(self, fields=None, using_db=None):
        if not self._saved_in_db:
            raise OperationalError("Can't refresh unpersisted record")
        names = tuple(fields) if fields is not None else tuple(
            self._meta.fields_db_projection
        )
        if not names:
            return
        query = self.__class__.all().using_db(using_db or self._choose_db())
        obj = await query.only(*names).get(pk=self.pk)
        for name in names:
            setattr(self, name, getattr(obj, name))
        # Cached relation objects must not survive a changed backing ID.
        for name in self._meta.fk_fields | self._meta.o2o_fields:
            source = self._meta.fields_map[name].source_field
            if source in names:
                self.__dict__.pop("_" + name, None)
