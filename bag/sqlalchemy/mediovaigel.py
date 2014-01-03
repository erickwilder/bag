# -*- coding: utf-8 -*-

'''Complete solution for database fixtures using SQLAlchemy.

This module is ALPHA software. You've been warned.

This solution has a very important feature: fixtures can be autogenerated
from an existing database, then applied to other databases.

You can use this as long as your models have a primary key column that is
consistently named (for instance, it is called "id" in all models).

The foreign key values stored in the fixtures are those of the original
database (from which the fixtures are generated). A translation is performed
in the fixture loading process. As fixtures are loaded, their new IDs are
stored in memory, and then the foreign keys referencing them get the new IDs,
not the ones written in the fixtures.

TODO: Support many-to-many (association tables).
'''

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from codecs import open
from datetime import date, datetime, timedelta
from decimal import Decimal
# from uuid import uuid4
from bag.sqlalchemy.tricks import model_property_names
from nine import nine, str
from .tricks import foreign_keys_in


class IndentWriter(object):
    def __init__(self):
        self.indentation = 0
        self.lines = []

    def indent(self):
        self.indentation += 4

    def dedent(self):
        self.indentation -= 4

    def add(self, line):
        self.lines.append(' ' * self.indentation + line)

    def __str__(self):
        return '\n'.join(self.lines)


@nine
class Mediovaigel(IndentWriter):
    '''Use this to generate SQLAlchemy fixtures from an existing database.
    The fixtures are expressed as Python code, so they sort of self-load.

    You can use Mediovaigel from a Python interpreter::

        from bag.sqlalchemy.mediovaigel import Mediovaigel
        from my.models import Course, Lecture, User, db
        m = Mediovaigel(db.session)
        m.generate_fixtures(Course)
        m.generate_fixtures(Lecture)
        m.generate_fixtures(User, blacklist_props=['id', 'password'])
        # (...)
        print(m.output())
        m.save_to('fixtures/generated.py')
    '''
    def __init__(self, db_session, pk_property_name='id'):
        super(Mediovaigel, self).__init__()
        self.sas = db_session
        self.pk = pk_property_name
        self.imports = ['import datetime']
        # self.refs = {}
        self.indent()

    def _serialize_property_value(self, entity, attrib, val):
        '''Returns a str containing the representation, or None.

        Override this in subclasses to support other types.
        '''
        if val is None or isinstance(val, (
                int, long, basestring, float, Decimal,
                date, datetime, timedelta)):
            return repr(val)

    def serialize_property_value(self, entity, attrib):
        val = self._serialize_property_value(
            entity, attrib, getattr(entity, attrib))
        if val:
            return val
        else:
            raise RuntimeError(
                'Cannot serialize. Entity: {}. Attrib: {}. Value: {}'.format(
                    entity, attrib, getattr(entity, attrib)))

    def generate_fixtures(self, cls, blacklist_props=['id']):
        '''``cls`` is the model class. ``blacklist_props`` is a list of the
        properties for this class that should not be passed when instantiating
        an entity.
        '''
        attribs = model_property_names(cls, blacklist=blacklist_props,
                                       include_relationships=False)
        assert len(attribs) > 0

        self.imports.append('from {} import {}'.format(
            cls.__module__, cls.__name__))
        for entity in self.sas.query(cls).yield_per(50):
            # if hasattr(entity, 'id'):
            #     ref = cls.__name__ + str(entity.id)
            # else:  # If there is no id, we generate our own random id:
            #     ref = cls.__name__ + str(uuid4())[-5:]
            # self.refs[ref] = entity
            # self.add('{} = {}('.format(ref, cls.__name__))
            self.add('yield ({}, {}('.format(
                getattr(entity, self.pk), cls.__name__))
            self.indent()

            for attrib in attribs:
                val = self.serialize_property_value(entity, attrib)
                self.add('{}={},'.format(attrib, val))

            self.dedent()
            self.add('))')
            # self.add('session.add({})\n'.format(ref))

    def output(self, encoding='utf-8'):
        '''Returns the final Python code with the fixture functions.'''
        return TEMPLATE.format(
            encoding=encoding, when=str(datetime.utcnow())[:16],
            imports='\n'.join(self.imports), pk=self.pk,
            the_fixtures='\n'.join(self.lines),
            )

    def save_to(self, path, encoding='utf-8'):
        with open(path, 'w', encoding=encoding) as writer:
            writer.write(self.output(encoding=encoding))


TEMPLATE = """\
# -*- coding: {encoding} -*-

'''Fixtures autogenerated by Mediovaigel on {when}'''

{imports}

PK = "{pk}"


def load_fixtures(session, fixtures=None, key_val_db=None, **kw):
    from bag.sqlalchemy.mediovaigel import load_fixtures
    load_fixtures(session, fixtures or the_fixtures(), key_val_db, PK=PK, **kw)


def the_fixtures():
{the_fixtures}
"""


def load_fixtures(session, fixtures, PK='id', key_val_db=None):
    mapp = key_val_db or {}  # maps original IDs to new IDs
    cached_fks = {}  # stores the foreign keys dict for each model class
    for index, tup in enumerate(fixtures):
        original_id, entity = tup
        cls = type(entity)
        key = cls.__tablename__ + str(original_id)
        fks = cached_fks.get(cls)
        if fks is None:
            fks = foreign_keys_in(cls)
            cached_fks[cls] = fks
        for fk_attrib, fk in fks.items():
            # Replace the old FK value with the NEW id stored in mapp
            new_id = mapp[fk.target_fullname.split('.')[0]
                          + getattr(entity, fk_attrib)]
            setattr(entity, fk_attrib, new_id)
        session.add(entity)
        session.flush()
        assert mapp.get(key) is None
        # Store the new id for this entity so we can look it up in the future:
        mapp[key] = getattr(entity, PK)  # 'course42': 37
        if index % 500 == 0:
            print(index)
    print('Committing...')
    session.commit()