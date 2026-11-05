-- Esquema idempotente: se aplica en cada arranque de la API.
-- Las sesiones y los días no se guardan: se calculan al consultar, porque un
-- dato atrasado puede unir sesiones o cambiar el día en que comienzan.

-- Un archivo cargado. El hash único evita aplicar dos veces el mismo contenido.
CREATE TABLE IF NOT EXISTS batches (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name      text        NOT NULL,
    file_sha256    char(64)    NOT NULL UNIQUE,
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    rows_read      integer     NOT NULL CHECK (rows_read >= 0),
    rows_valid     integer     NOT NULL CHECK (rows_valid >= 0),
    rows_discarded integer     NOT NULL CHECK (rows_discarded >= 0),
    CONSTRAINT batches_rows_add_up CHECK (rows_read = rows_valid + rows_discarded)
);

-- Filas descartadas de cada archivo, agrupadas por motivo.
CREATE TABLE IF NOT EXISTS batch_rejections (
    batch_id bigint  NOT NULL REFERENCES batches (id) ON DELETE CASCADE,
    reason   text    NOT NULL,
    rows     integer NOT NULL CHECK (rows > 0),
    PRIMARY KEY (batch_id, reason)
);

-- Una fila por dispositivo e instante: la última recibida. La clave primaria
-- también sirve para recorrer las lecturas de un dispositivo en orden de tiempo.
CREATE TABLE IF NOT EXISTS readings (
    device_id   text             NOT NULL,
    recorded_at timestamptz      NOT NULL,
    value       numeric,          -- NULL: sin dato; no participa en el promedio.
    lat         double precision, -- lat y lon en NULL: sin posición; no se dibuja.
    lon         double precision,
    batch_id    bigint           NOT NULL REFERENCES batches (id),
    source_line integer          NOT NULL CHECK (source_line > 0),
    PRIMARY KEY (device_id, recorded_at),
    CONSTRAINT readings_device_id_normalized
        CHECK (device_id <> '' AND device_id = upper(btrim(device_id))),
    -- En numeric, NaN e Infinity son valores válidos y arruinarían el promedio.
    CONSTRAINT readings_value_finite
        CHECK (value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)),
    CONSTRAINT readings_position_complete
        CHECK ((lat IS NULL) = (lon IS NULL)),
    CONSTRAINT readings_position_valid
        CHECK (lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180 AND NOT (lat = 0 AND lon = 0))
);
