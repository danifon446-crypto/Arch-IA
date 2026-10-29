-- =====================================================================
-- Arché: memoria en la nube + turnos sin PC  (Fases 2 y 3)
-- =====================================================================
-- Pégalo completo en Supabase -> SQL Editor -> New query -> Run.
-- Se puede correr varias veces: no borra nada de lo que ya tengas
-- (ni las tablas de la red de aprendizaje).
--
-- Seguridad: las 4 tablas tienen RLS activado y NINGUNA política, así
-- que con la clave pública (anon/publishable) no se puede leer ni
-- escribir nada. Solo entra la clave secreta (service_role / sb_secret),
-- que vive cifrada en tu PC y en los Secrets de GitHub.
-- =====================================================================

-- Lo que Arché aprendió (de tu PC o de los turnos en la nube).
-- Solo frases de órdenes: nada de charlas, memoria, notas ni WhatsApp.
create table if not exists public.arche_ejemplos (
    id           bigserial primary key,
    frase        text        not null check (char_length(frase) between 2 and 150),
    intencion    text        not null,
    contenido    text        not null default '' check (char_length(contenido) <= 40),
    origen       text        not null,              -- 'pc' | 'turno_huecos' | 'turno_dificiles'
    pc           text        not null default '',   -- id anónimo del PC, o 'nube'
    validado_por text        not null default '',   -- modelo que confirmó la intención
    creado       timestamptz not null default now(),
    retirado     boolean     not null default false, -- true = se quita de todos los PC
    unique (frase, intencion)
);
create index if not exists arche_ejemplos_id_pc on public.arche_ejemplos (id, pc);

-- Cuántos ejemplos tiene cada intención en tu PC (solo números, sin frases).
-- Con esto el turno de la nube sabe dónde están los huecos.
create table if not exists public.arche_conteos (
    intencion   text primary key,
    ejemplos    integer     not null default 0,
    actualizado timestamptz not null default now()
);

-- Bitácora de cada turno (sirve también para la cuota diaria).
create table if not exists public.arche_turnos (
    id         bigserial primary key,
    tarea      text        not null,
    inicio     timestamptz not null default now(),
    pedidos    integer     not null default 0,   -- llamadas a la nube gastadas
    aceptados  integer     not null default 0,
    rechazados integer     not null default 0,
    nota       text        not null default ''
);

-- Interruptores y cuotas. Se cambian desde Arché ("apaga los turnos de la nube")
-- o aquí mismo en Supabase (Table Editor -> arche_config).
create table if not exists public.arche_config (
    clave text primary key,
    valor jsonb not null
);
insert into public.arche_config (clave, valor) values
    ('turnos_activos', 'true'),
    ('cuota_diaria',   '{"huecos": 120, "dificiles": 60}')
on conflict (clave) do nothing;

alter table public.arche_ejemplos enable row level security;
alter table public.arche_conteos  enable row level security;
alter table public.arche_turnos   enable row level security;
alter table public.arche_config   enable row level security;
