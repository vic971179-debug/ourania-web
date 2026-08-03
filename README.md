# Ourania — backend web

Microservicio de cálculo astrológico (FastAPI + [pyswisseph](https://github.com/astrorigin/pyswisseph),
motor Moshier) que da soporte a la versión web liviana de
[Ourania](https://vpardo.com/ourania), la app de escritorio de astrología.

Sin persistencia, sin autenticación: cada carta se calcula al vuelo a
partir de los datos de nacimiento recibidos, y no se guarda nada.

## Por qué este repo es público

Swiss Ephemeris (la librería astronómica que usa `pyswisseph`) tiene
licencia dual: AGPL gratuita, o licencia profesional paga. La AGPL exige
que cualquier software accesible por red que la use publique su código
fuente. Este repo es exactamente eso — el componente público que cumple
esa condición. El resto de Ourania (app de escritorio) es un proyecto
aparte y privado, sin relación de licencia con este repo.

## Stack

- `api/main.py` — FastAPI, calcula posiciones/casas/aspectos/dignidades/
  tránsitos/revoluciones vía Swiss Ephemeris (modo Moshier).
- `public/index.html` — frontend estático sin build (HTML+JS plano),
  sin frameworks.
- Deploy: Vercel (`@vercel/python` para el backend, estático para el frontend).

## Desarrollo local

```bash
cd api
python3 -m venv ../.venv && source ../.venv/bin/activate
pip install -r ../requirements.txt
uvicorn main:app --port 8790
```

El frontend (`public/index.html`) asume mismo origen (`/api/*` ruteado al
backend vía `vercel.json`) — para probarlo local contra un backend en otro
puerto, cambiar temporalmente la constante `API` en el `<script>`.
