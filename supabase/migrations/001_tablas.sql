-- LimitBar · tablas v0
-- Pegar en Supabase → SQL Editor → Run. Se puede ejecutar más de una vez sin romper nada.

-- Último estado: una fila por proveedor. El recolector la sobrescribe en cada ronda.
create table if not exists public.latest_status (
  provider        text primary key,                 -- "claude", "gemini"…
  status          text not null check (status in ('ok', 'error')),
  error           text,
  windows         jsonb,                            -- [{id, label, used_pct, resets_at}], formato v0
  checked_at      timestamptz not null,             -- última vez que se intentó leer
  updated_at      timestamptz,                      -- última lectura buena (lo que enseña «hace X min»)
  source_device   text not null,
  schema_version  int not null default 0
);

-- Histórico: una fila por ventana y ronda, solo de las lecturas buenas.
create table if not exists public.usage_history (
  id              bigint generated always as identity primary key,
  collected_at    timestamptz not null,
  provider        text not null,
  window_id       text not null,                    -- "5h", "7d"…
  used_pct        numeric(5, 1),
  resets_at       timestamptz,
  source_device   text not null
);

create index if not exists usage_history_lookup
  on public.usage_history (provider, window_id, collected_at desc);

-- Seguridad: RLS activado y sin políticas → nadie lee ni escribe con la clave pública.
-- El Mac escribe con la clave secreta (se salta RLS). La lectura del widget se decide en la fase 3.
alter table public.latest_status enable row level security;
alter table public.usage_history enable row level security;
