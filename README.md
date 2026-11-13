# Pulso: datos abiertos de terrazas (Madrid y València)

Código abierto de dos webs estáticas y gratuitas que convierten datos municipales abiertos en tablas, gráficos y CSV listos para reutilizar:

- **Pulso Local Madrid**: https://paniset.github.io/pulso-local-madrid/
  - Compara cortes mensuales del censo de terrazas de hostelería.
  - Lo cruza con el padrón por distrito y barrio.
  - Muestra la evolución mensual, la superficie y las sillas autorizadas.
- **Pulso València**: https://paniset.github.io/pulso-valencia/
  - Recibos de la tasa de mesas y sillas por distrito y barrio (2020-2025).

## Fuentes
| Ciudad | Conjunto | Licencia |
|---|---|---|
| Madrid | [Censo de locales, sus actividades y terrazas de hostelería y restauración. Histórico](https://datos.madrid.es/dataset/209548-0-censo-locales-historico) | CC BY 4.0 |
| Madrid | [Población por distrito y barrio a 1 de enero](https://datos.madrid.es/dataset/300557-0-poblacion-distrito-barrio) | CC BY 4.0 |
| València | [Recibos mesas y sillas 2020 - 2025](https://opendata.vlci.valencia.es/dataset/recibos-mesas-y-sillas-2020-2025) | CC BY 4.0 |

## Cómo se garantiza la calidad
- **Ficheros fijados:** cada fichero de origen queda fijado por URL, tamaño y huella SHA-256. Si la fuente cambia un fichero ya incorporado, el proceso se detiene en lugar de publicar datos distintos.
- **Esquema estricto:** `factory/radar_schema.py` comprueba los totales (por ejemplo, que los barrios sumen su distrito y que la serie mensual termine en el corte comparado).
- **Privacidad:** solo se guardan agregados o identificadores administrativos, sin nombres, direcciones ni coordenadas. En València, el tipo de titular solo se publica por distrito y el importe por barrio solo con 5 o más recibos.
- **Páginas seguras:** las páginas generadas llevan una política de seguridad de contenido estricta (CSP), sin scripts ni estilos en línea.

## Uso
Requiere Python 3.11 o superior y Node 20 o superior (para las pruebas de JavaScript). No hay dependencias externas.

```bash
python -m unittest discover -s tests      # pruebas de Python
node --test tests/*.test.mjs              # pruebas del frontal
python scripts/build.py                   # genera dist/ (Pulso Madrid) a partir de data/
python scripts/pulso_valencia.py          # genera la página de València
```

**Actualizar con datos nuevos** (necesita red):
- Madrid:
  - `python scripts/pulso_nuevo_corte.py`, y con `--apply` si hay un corte nuevo;
  - `python scripts/madrid.py`;
  - `python scripts/madrid_serie.py`;
  - `python scripts/madrid.py --offline`.
- Padrón: `python scripts/madrid_poblacion.py`.
- València: `python scripts/pulso_valencia.py --descargar`.

## Licencias
- **Código:** MIT (ver `LICENSE`).
- **Datos derivados** de `data/` y de los CSV generados: CC BY 4.0. Atribución: Ayuntamiento de Madrid y Ajuntament de València. Transformado por Pulso Local.

## Avisos
- Un cambio en el registro o un recibo de la tasa no prueban que un local haya abierto, cerrado o tenga la terraza montada.
- Las cifras por habitante usan la población empadronada y no miden saturación.
- Este proyecto no interpreta la normativa municipal.

Sugerencias y errores: abre una incidencia en este repositorio, sin datos personales.
