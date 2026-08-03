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

- `main.py` — FastAPI, calcula posiciones/casas/aspectos/dignidades/
  tránsitos/revoluciones vía Swiss Ephemeris (modo Moshier). Vive en la
  RAÍZ del repo (no adentro de `api/`) porque `api/index.py` hace
  `from main import app` y Vercel solo pone la raíz del proyecto en
  `sys.path`, no la carpeta de la función — moverlo adentro de `api/`
  rompe el import en producción (`ModuleNotFoundError: No module named 'main'`),
  aunque ande perfecto en local.
- `api/index.py` — un solo `from main import app`, el entrypoint que
  espera `@vercel/python`.
- `ephe/` — igual, en la raíz (junto a `main.py`, no adentro de `api/`).
- `public/index.html` — frontend estático sin build (HTML+JS plano),
  sin frameworks.
- Deploy: Vercel (`@vercel/python` para el backend, estático para el frontend).
  **Deployment Protection (SSO) tiene que estar OFF** para este proyecto —
  por default Vercel bloquea con un login de Vercel cualquier acceso a los
  `*.vercel.app`, lo cual rompe el propósito (acceso público sin cuenta).

## Desarrollo local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8790
```

El frontend (`public/index.html`) asume mismo origen (`/api/*` ruteado al
backend vía `vercel.json`) — para probarlo local contra un backend en otro
puerto, cambiar temporalmente la constante `API` en el `<script>`.
