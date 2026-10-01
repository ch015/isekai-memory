"""Local lexical ranking, retaining authorization before LIMIT and hydration.

No model, vector service or search extension is needed. Scores are local lexical
scores, not numerically interchangeable with PostgreSQL ts_rank_cd.
"""
from .postgres import PostgresLexical


class SQLiteLexical(PostgresLexical):
    name = 'sqlite_lexical'
    _match = """
        memory_lexical_match(search_text,$6) OR NOT EXISTS (
            SELECT 1 FROM json_each($7) AS terms WHERE instr(search_text,terms.value)=0
        )
    """
    _rank = 'memory_lexical_rank(search_text,$6)'

    def __init__(self, *, weighted=False):
        if weighted:
            self.name = 'sqlite_weighted_lexical'
            self._rank = ("3*memory_lexical_rank(title,$6) + "
                          "2*memory_lexical_rank(array_to_string(tags,' '),$6) + "
                          "memory_lexical_rank(content,$6)")
