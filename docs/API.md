# API del servicio de lecturas

Guía para conectar el frontend. La documentación interactiva está en `http://localhost:8000/docs`.

- **URL base:** `http://localhost:8000`
- **Formato:** respuestas en JSON
- **Autenticación:** ninguna
- **CORS:** permite los orígenes de `CORS_ORIGINS` en `.env`. Si tu frontend usa otro puerto, agrégalo separado por coma y ejecuta `docker compose up -d`.

## Endpoints

| Método | Ruta | Devuelve |
| :--- | :--- | :--- |
| `GET` | `/health` | Estado de la API y de la base |
| `POST` | `/batches` | Carga un archivo CSV y devuelve su resumen |
| `GET` | `/devices` | Dispositivos con datos |
| `GET` | `/devices/{device_id}/days/{YYYY-MM-DD}` | Resumen de un día |
| `GET` | `/devices/{device_id}/days/{YYYY-MM-DD}/track` | Recorrido de un día en GeoJSON |

`device_id` no distingue mayúsculas de minúsculas. Las fechas se interpretan en hora de `America/Santiago`.

## `POST /batches`

Carga **un archivo por petición**, en el campo `file` de un formulario `multipart/form-data`, con un máximo de 50 MB.

```js
async function uploadBatch(file) {
  const body = new FormData();
  body.append("file", file);

  // No definas Content-Type: el navegador lo agrega con su separador.
  const response = await fetch("http://localhost:8000/batches", { method: "POST", body });
  if (!response.ok) throw new Error((await response.json()).detail);
  return response.json();
}
```

```json
{
  "file_name": "lote_1.csv",
  "already_loaded": false,
  "rows_read": 79698,
  "rows_valid": 79496,
  "rows_discarded": 202,
  "rejections": {
    "device_id_vacio": 47,
    "fecha_invalida": 48,
    "fecha_sin_zona_horaria": 107
  },
  "inserted": 79100,
  "updated": 0
}
```

| Campo | Significado |
| :--- | :--- |
| `already_loaded` | `true` si ese contenido ya se había cargado: no cambió nada |
| `rows_read` | Filas leídas |
| `rows_valid` | Filas válidas, incluidas las repetidas dentro del archivo |
| `rows_discarded` | Filas descartadas; es la suma de `rejections` |
| `rejections` | Filas descartadas por motivo; `{}` si no hay ninguna |
| `inserted` | Lecturas nuevas |
| `updated` | Lecturas existentes que este archivo reemplazó |

Motivos posibles de descarte: `columnas_incorrectas`, `device_id_vacio`, `fecha_invalida`, `fecha_sin_zona_horaria` y `value_no_numerico`.

**Es idempotente:** subir el mismo contenido otra vez, incluso con otro nombre o varias veces a la vez, responde `200` con `already_loaded: true` y no crea duplicados ni cambia datos. En ese caso, muestra "Este archivo ya estaba cargado" en lugar de un error.

**El orden importa:** vale el archivo que se carga después. Si subes varios, envíalos uno a la vez y espera cada respuesta. Después de una carga, vuelve a pedir `GET /devices` para refrescar la lista.

## `GET /devices`

Devuelve los dispositivos ordenados por `device_id`, o `[]` si no hay datos.

```json
[
  { "device_id": "D-0001", "first_day": "2026-09-04", "last_day": "2026-09-07" }
]
```

`first_day` y `last_day` son los días de la primera y la última lectura. Sirven para limitar el selector de fecha.

## `GET /devices/{device_id}/days/{YYYY-MM-DD}`

```json
{
  "device_id": "D-0001",
  "date": "2026-09-05",
  "readings": 812,
  "avg_value": 51.23,
  "sessions": [
    {
      "start": "2026-09-05T10:15:02-04:00",
      "end": "2026-09-05T12:01:40-04:00",
      "readings": 97,
      "duration_min": 106.63
    }
  ]
}
```

| Campo | Significado |
| :--- | :--- |
| `readings` | Lecturas cuyo instante cae en ese día |
| `avg_value` | Promedio de los valores con dato, con 2 decimales; `null` si no hay ninguno |
| `sessions` | Sesiones que **comienzan** ese día, ordenadas por inicio |
| `sessions[].readings` | Lecturas de la sesión completa, aunque termine al día siguiente |
| `sessions[].duration_min` | `end - start` en minutos, con 2 decimales |

La suma de `sessions[].readings` puede no coincidir con `readings`, porque una sesión puede cruzar la medianoche.

Un día sin lecturas de un dispositivo existente responde `200`:

```json
{ "device_id": "D-0001", "date": "2026-09-10", "readings": 0, "avg_value": null, "sessions": [] }
```

## `GET /devices/{device_id}/days/{YYYY-MM-DD}/track`

Devuelve un `Feature` por sesión, con las mismas sesiones y en el mismo orden que el resumen. Por eso, el índice de cada `Feature` identifica su sesión en la lista.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [[-70.6483, -33.4372], [-70.6471, -33.4365]]
      },
      "properties": {
        "start": "2026-09-05T10:15:02-04:00",
        "end": "2026-09-05T12:01:40-04:00",
        "readings": 97,
        "positions": 95
      }
    }
  ]
}
```

`geometry` depende de cuántos puntos con posición tenga la sesión (`positions`):

| Puntos | `geometry` |
| :--- | :--- |
| 2 o más | `LineString` |
| 1 | `Point` |
| 0 | `null`: la sesión aparece en la lista, pero no se dibuja |

Las coordenadas van en orden **`[lon, lat]`**. Leaflet usa `[lat, lon]` si creas las capas a mano, pero `L.geoJSON` hace la conversión.

## Errores

Los errores responden con el campo `detail`:

```json
{ "detail": "Dispositivo no encontrado: D-9999" }
```

La única excepción es un `POST /batches` sin el campo `file`: responde `422` y `detail` es una lista con el detalle de la validación.

| Código | Cuándo | Qué mostrar |
| :--- | :--- | :--- |
| `404` | El dispositivo no existe | Dispositivo inexistente |
| `413` | El archivo supera los 50 MB | Archivo demasiado grande |
| `422` | La fecha no es válida o no usa `YYYY-MM-DD`, o el archivo no se puede interpretar | El mensaje de `detail` |
| `503` | La base de datos no está disponible | Servicio no disponible |
| Sin respuesta | La API está apagada | Error de conexión con la API |

## Fechas en el frontend

Muestra siempre la hora de Santiago, aunque el navegador esté en otra zona horaria:

```js
new Intl.DateTimeFormat("es-CL", {
  timeZone: "America/Santiago",
  dateStyle: "short",
  timeStyle: "medium",
}).format(new Date("2026-09-05T10:15:02-04:00"));
```

Para pasar al día anterior o siguiente, opera sobre el texto `YYYY-MM-DD` en UTC y no con la hora local del navegador. El 6 de septiembre de 2026 Chile cambia de horario: ese día tiene 23 horas y no existe la medianoche.

```js
function addDays(day, amount) {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}
```
