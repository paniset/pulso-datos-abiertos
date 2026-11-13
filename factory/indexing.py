"""Explicit indexing policy: only fixed approved project/template pairs."""
import html
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element, SubElement, tostring

APPROVED = {
    ('kit-de-vuelta', 'custom'): ('https://paniset.github.io/kit-de-vuelta', {'index.html':'/', 'control-prestamo-material.html':'/control-prestamo-material',
        'plantilla-prestamo-material.html':'/plantilla-prestamo-material',
        'material-prestamo-colegio-ampa.html':'/material-prestamo-colegio-ampa',
        'control-material-grupo-scout.html':'/control-material-grupo-scout',
        'prestamo-herramientas-biblioteca-de-las-cosas.html':'/prestamo-herramientas-biblioteca-de-las-cosas',
        'acta-entrega-devolucion-equipos-empleados.html':'/acta-entrega-devolucion-equipos-empleados',
        'prestamo-equipos-audiovisuales.html':'/prestamo-equipos-audiovisuales'}),
    ('pulso-local', 'radar'): ('https://paniset.github.io/pulso-local-madrid', {'index.html':'/', 'muestra.html':'/muestra',
        'terrazas-madrid-por-distrito.html':'/terrazas-madrid-por-distrito',
        'como-leer-censo-terrazas-madrid.html':'/como-leer-censo-terrazas-madrid',
        'evolucion-terrazas-madrid.html':'/evolucion-terrazas-madrid',
        'terrazas-madrid-por-barrio.html':'/terrazas-madrid-por-barrio',
        'superficie-terrazas-madrid.html':'/superficie-terrazas-madrid'}),
    ('turno-facil', 'custom'): ('https://paniset.github.io/turno-facil', {'index.html':'/',
        'reparto-tareas-piso-compartido.html':'/reparto-tareas-piso-compartido', 'reparto-tareas-pareja.html':'/reparto-tareas-pareja',
        'cuadrante-limpieza-piso-compartido.html':'/cuadrante-limpieza-piso-compartido',
        'tabla-tareas-hogar-frecuencia-minutos.html':'/tabla-tareas-hogar-frecuencia-minutos',
        'companero-piso-no-cumple-turno-limpieza.html':'/companero-piso-no-cumple-turno-limpieza',
        'reparto-tareas-casa-con-hijos.html':'/reparto-tareas-casa-con-hijos',
        'normas-convivencia-piso-compartido.html':'/normas-convivencia-piso-compartido'}),
}
# Etiqueta de Search Console del usuario para el dominio paniset.github.io: Google da una por
# usuario y dominio, así que sirve para las tres propiedades. Es pública por diseño.
SEARCH_CONSOLE_TOKEN = 'yU-MmDAEv0MF0oqv6WEPJR-Wn4J0yyzl8J-dgcel0is'

def page_metadata(page,title=None,description=None,canonical=None,social=False,verification=None,image=None):
    """Edit parsed head tags by offsets; script/style/comment bytes stay intact."""
    offsets=[0]+[index+1 for index,char in enumerate(page) if char=='\n']
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.tags=[];self.inert=0;self.doctype_end=0
        def position(self):
            line,column=self.getpos();return offsets[line-1]+column
        def handle_starttag(self,tag,attrs):
            start=self.position();raw=self.get_starttag_text()
            self.tags.append((tag,start,start+len(raw),dict(attrs),self.inert))
            if tag=='template':self.inert+=1
        def handle_startendtag(self,tag,attrs):
            self.handle_starttag(tag,attrs)
            if tag=='template':self.inert-=1
        def handle_decl(self,decl):
            if decl.lower().startswith('doctype ') and not self.tags:
                self.doctype_end=page.find('>',self.position())+1
        def handle_endtag(self,tag):
            start=self.position();end=page.find('>',start)
            self.tags.append(('/'+tag,start,len(page) if end<0 else end+1,{},self.inert))
            if tag=='template':self.inert=max(0,self.inert-1)
    parsed=Tags();parsed.feed(page);parsed.close()
    tags=[entry for entry in parsed.tags if not entry[4]]
    head=next((entry for entry in tags if entry[0]=='head'),None)
    if head:
        left=head[2]
        right=next((entry[1] for entry in tags if entry[1]>=left and entry[0] in {'/head','body'}),len(page))
    else:
        opening=next((entry for entry in tags if entry[0]=='html'),None)
        left=opening[2] if opening else parsed.doctype_end
        head_tags={'html','head','title','base','link','meta','style','script','noscript','template'}
        right=next((entry[1] for entry in tags if entry[1]>=left and not entry[0].startswith('/') and entry[0] not in head_tags),len(page))
    edits=[];title_start=None;title_content=None
    final_title=title;final_description=description
    for tag,start,end,attrs,_ in tags:
        if not left<=start<right:continue
        if tag=='title' and title_start is None:
            title_start=start;title_content=end
        elif tag=='/title' and title_start is not None:
            if final_title is None:final_title=html.unescape(page[title_content:start])
            if title is not None:edits.append((title_start,end,''))
            title_start=None
        elif title_start is None:
            if tag=='meta':
                name=(attrs.get('name') or '').lower()
                properties=[name,(attrs.get('property') or '').lower()]
                if name=='description' and final_description is None:final_description=attrs.get('content')
                if (name in {'robots','googlebot','bingbot','google-site-verification'} or (description is not None and name=='description')
                        or (social and any(value.startswith(('og:','twitter:')) for value in properties))):
                    edits.append((start,end,''))
            elif tag=='link' and 'canonical' in (attrs.get('rel') or '').lower().split():
                edits.append((start,end,''))
    if title_start is not None:
        raise ValueError('El título HTML debe cerrarse antes de construir el candidato')
    metadata = '<meta name="robots" content="' + ('index,follow' if canonical else 'noindex,follow') + '">'
    if title is not None: metadata += f'<title>{html.escape(title)}</title>'
    if description is not None: metadata += f'<meta name="description" content="{html.escape(description,quote=True)}">'
    if canonical: metadata += f'<link rel="canonical" href="{html.escape(canonical,quote=True)}">'
    if verification: metadata += f'<meta name="google-site-verification" content="{html.escape(verification,quote=True)}">'
    if social:
        # Run after the pipeline's title/description override. Never trust source social URLs.
        values=[('property','og:type','website'),('property','og:locale','es_ES'),
                ('name','twitter:card','summary_large_image' if image else 'summary')]
        if final_title is not None:
            values.extend([('property','og:title',final_title),('name','twitter:title',final_title)])
        if final_description is not None:
            values.extend([('property','og:description',final_description),('name','twitter:description',final_description)])
        if canonical:values.append(('property','og:url',canonical))
        if image:
            values.extend([('property','og:image',image),('property','og:image:width','1200'),
                           ('property','og:image:height','630'),('name','twitter:image',image)])
        metadata+=''.join(f'<meta {attribute}="{key}" content="{html.escape(value,quote=True)}">'
                          for attribute,key,value in values)
    if head:edits.append((left,left,metadata))
    elif left==right:edits.append((left,left,'<head>'+metadata+'</head>'))
    else:
        edits.append((left,left,'<head>'+metadata))
        edits.append((right,right,'</head>'))
    for start,end,replacement in sorted(edits,key=lambda item:(item[0],item[1]),reverse=True):
        page=page[:start]+replacement+page[end:]
    return page


def apply_indexing(content, project_id, template):
    """Return a new inventory; source URLs/config cannot authorize indexing."""
    result = dict(content)
    origin, routes = APPROVED.get((project_id, template), ('', {}))
    if template=='custom':
        # En GitHub Pages la web vive en una subruta: «/» sería la raíz de la cuenta, no la web.
        home = html.escape(origin + '/', quote=True) if origin else '/'
        result.setdefault('404.html', ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
                          '<meta name="viewport" content="width=device-width,initial-scale=1">'
                          '<title>Página no encontrada</title></head><body><h1>Página no encontrada</h1>'
                          f'<p>La dirección solicitada no existe.</p><a href="{home}">Volver al inicio</a></body></html>').encode('utf-8'))
    urls = []
    for name, raw in list(result.items()):
        if PurePosixPath(name).suffix.lower() != '.html':
            continue
        canonical = origin + routes[name] if name in routes else None
        # Solo la portada de una web aprobada lleva la verificación; las fuentes no pueden aportarla.
        verification = SEARCH_CONSOLE_TOKEN if name in routes and routes[name] == '/' else None
        # Imagen para compartir solo en páginas aprobadas y si la web la incluye (og.png, 1200x630).
        image = origin + '/og.png' if canonical and 'og.png' in result else None
        result[name] = page_metadata(raw.decode('utf-8-sig'), canonical=canonical, social=True,
                                     verification=verification, image=image).encode('utf-8')
        if canonical: urls.append(canonical)
    # Never carry a source-authored sitemap or robots declaration into a build.
    result.pop('sitemap.xml', None)
    robots = 'User-agent: *\nAllow: /\n'
    if urls:
        tree = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
        for url in sorted(urls):
            SubElement(SubElement(tree, 'url'), 'loc').text = url
        result['sitemap.xml'] = tostring(tree, encoding='utf-8', xml_declaration=True)
        robots += f'Sitemap: {origin}/sitemap.xml\n'
    result['robots.txt'] = robots.encode('utf-8')
    return result
