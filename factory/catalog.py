"""Fixed tools and bounded static-site generation; never copy a checkout."""
from pathlib import Path

PUBLIC_FILES=("index.html","app.js","lib.mjs","style.css","favicon.svg","legal.html")
# La guía es estática (site/), pero la entrega sample_files: así la copian el pipeline y scripts/build.py.
RADAR_GENERATED_FILES=("muestra.html","muestra.css","pulso-muestra.csv","terrazas-madrid-por-distrito.html","terrazas-madrid-distritos.csv","evolucion-terrazas-madrid.html","terrazas-madrid-evolucion.csv","terrazas-madrid-por-barrio.html","terrazas-madrid-barrios.csv","superficie-terrazas-madrid.html","terrazas-madrid-superficie.csv","como-leer-censo-terrazas-madrid.html","og.png")
TEMPLATES={
    "radar":{"title":"Radar de datos públicos","directory":"site","files":PUBLIC_FILES,"generated_files":RADAR_GENERATED_FILES,"data":"data/radar.json"},
    "plazo-claro":{"title":"Plazo Claro · calendario local","directory":"sites/plazo-claro/site","files":PUBLIC_FILES,"data":None},
    "custom":{"title":"Web nueva desde una idea","directory":None,"files":("index.html",),"data":None,
              "source_pattern":"sites/<id>/site","requires_generation":True},
}


def get_template(template_id):
    if not isinstance(template_id,str) or template_id not in TEMPLATES:
        raise ValueError("Plantilla no reconocida")
    return TEMPLATES[template_id]


def catalog(workspace):
    workspace=Path(workspace).resolve()
    result=[]
    for identifier,template in TEMPLATES.items():
        if template.get("requires_generation"):
            result.append({"id":identifier,"title":template["title"],"available":True,"missing":[],
                           "files":list(template["files"]),"source_pattern":template["source_pattern"],"requires_generation":True})
            continue
        required=[workspace/template["directory"]/name for name in template["files"]]
        if template["data"]:
            required.append(workspace/template["data"])
        missing=[str(path.relative_to(workspace)).replace('\\','/') for path in required if not path.is_file()]
        result.append({"id":identifier,"title":template["title"],"available":not missing,"missing":missing,
                       "files":list(template["files"])+list(template.get("generated_files",()))+([template["data"]] if template["data"] else [])})
    return result
