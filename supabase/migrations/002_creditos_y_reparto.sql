-- LimitBar · reparto del uso por producto (Claude Code, chats, Cowork…)
-- Las ventanas ganan campos opcionales (kind, used, limit, currency) dentro del jsonb: no hace
-- falta tocar la tabla para eso.
alter table public.latest_status add column if not exists breakdown jsonb;   -- [{id, label, pct}]
