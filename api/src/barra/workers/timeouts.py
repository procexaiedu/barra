"""Cron: varre interrupts pendentes do LangGraph e escala se exceder prazo.

LangGraph 0.4 não tem TTL nativo para interrupt(); este worker cobre o caso.
"""
