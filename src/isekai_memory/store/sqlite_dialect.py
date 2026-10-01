"""Compile repository SQL to SQLite; values remain bound, never interpolated.

SQLGlot handles syntax, not concurrency. SQLiteConnection enforces transaction
locks separately. This is an adapter for our repository queries, not a general
PostgreSQL emulation layer. Unsupported constructs fail instead of being omitted.
"""
from functools import lru_cache

from sqlglot import ErrorLevel, exp, parse_one
from sqlglot.dialects.postgres import Postgres
from sqlglot.tokens import TokenType


class RepositoryPostgres(Postgres):
    class Tokenizer(Postgres.Tokenizer):
        # Runtime queries have parameters, never dollar-quoted function bodies.
        # Disambiguate adjacent $1,$2 placeholders without editing SQL strings.
        HEREDOC_STRINGS = []
        SINGLE_TOKENS = {**Postgres.Tokenizer.SINGLE_TOKENS, '$': TokenType.PARAMETER}


def call(name, *args):
    return exp.Anonymous(this=name, expressions=list(args))


def _interval(node):
    if isinstance(node, exp.Interval):
        unit = node.args['unit'].name.lower().rstrip('s')
        seconds = {'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400}[unit]
        return exp.Mul(this=exp.Literal.number(node.this.this), expression=exp.Literal.number(seconds))
    if isinstance(node, exp.MakeInterval):
        value = node.args.get('year')
        if not isinstance(value, exp.Kwarg) or value.this.name.lower() != 'secs':
            raise ValueError('Only second-based make_interval is supported')
        return value.expression
    if isinstance(node, exp.Mul) and isinstance(node.expression, exp.Interval):
        return exp.Mul(this=node.this, expression=_interval(node.expression))
    return None


def _rewrite(node):
    if isinstance(node, exp.Parameter):
        return exp.Placeholder(this='p' + node.this.name)
    if isinstance(node, exp.Cast):
        kind = node.to.this.value
        if kind == 'UUID':
            return call('memory_uuid', node.this)
        if kind in {'TIMESTAMPTZ', 'TIMESTAMP'}:
            return call('memory_timestamp', node.this)
        if kind in {'JSONB', 'JSON', 'ARRAY'}:
            return node.this
    if isinstance(node, exp.CurrentTimestamp):
        return call('transaction_timestamp')
    if isinstance(node, exp.Uuid):
        return call('gen_random_uuid')
    if isinstance(node, (exp.Add, exp.Sub)):
        seconds = _interval(node.expression)
        if seconds is not None:
            if isinstance(node, exp.Sub):
                seconds = exp.Neg(this=exp.Paren(this=seconds))
            return call('memory_shift_time', node.this, seconds)
    if isinstance(node, exp.EQ) and isinstance(node.expression, exp.Any):
        value = node.expression.this.unnest()
        return call('memory_array_contains', value, node.this)
    if isinstance(node, exp.Array):
        return call('json_array', *node.expressions)
    if isinstance(node, exp.ILike):
        return call('memory_ilike', node.this, node.expression)
    if isinstance(node, exp.MatchAgainst):
        return call('memory_lexical_match', node.expressions[0], node.this)
    if isinstance(node, exp.Left):
        return call('substr', node.this, exp.Literal.number(1), node.expression)
    if isinstance(node, exp.RegexpLike):
        return call('regexp', node.expression, node.this)
    if isinstance(node, exp.Anonymous):
        name = node.name.lower()
        if name in {'to_tsvector', 'plainto_tsquery'}:
            return node.expressions[-1]
        if name == 'setweight':
            return node.expressions[0]
        if name == 'ts_rank_cd':
            return call('memory_lexical_rank', *node.expressions)
    return node


def expression(sql):
    tree = parse_one(sql, read=RepositoryPostgres)
    for select in tree.find_all(exp.Select):
        for projection in list(select.expressions):
            if isinstance(projection, exp.Cast) and isinstance(projection.this, exp.Column):
                projection.replace(exp.alias_(projection.copy(), projection.this.name))
    # Bottom-up replacement also handles parameters inside replacement nodes.
    for node in reversed(list(tree.walk())):
        replacement = _rewrite(node)
        if replacement is not node:
            if node is tree:
                tree = replacement
            else:
                node.replace(replacement)
    return tree


@lru_cache(maxsize=512)
def compile_query(sql):
    tree = expression(sql)
    locked = False
    for select in tree.find_all(exp.Select):
        if select.args.get('locks'):
            locked = True
            select.set('locks', None)
    # SQLite RETURNING cannot qualify target columns, unlike PostgreSQL.
    for returning in tree.find_all(exp.Returning):
        for column in returning.find_all(exp.Column):
            column.set('table', None)
    for conflict in tree.find_all(exp.OnConflict):
        for ordered in conflict.find_all(exp.Ordered):
            ordered.set('nulls_first', not ordered.args.get('desc'))
    return tree.sql(dialect='sqlite', unsupported_level=ErrorLevel.RAISE), locked
