-- LimitBar · coste equivalente por modelo (tokens de Claude Code valorados con la tabla de precios)
alter table public.latest_status add column if not exists cost jsonb;
  -- {window_days, priced_usd, prices_revised, models:[{model,label,input,output,cache_write,cache_read,cost_usd}]}
