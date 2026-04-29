"""AsyncConnectionPool psycopg3 contra Supavisor (porta 6543, transaction mode).

Pool criado uma vez no lifespan; nunca usar from_conn_string em produção.
"""
