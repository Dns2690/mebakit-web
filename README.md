# MEBAKIT — sitio web

Página de producto de MEBAKIT, estación portátil para trabajos electrónicos desarrollada por estudiantes de Ingeniería Mecatrónica de Universidad Invenio.

La especificación completa (diseño, textos, criterios de aceptación) está en el documento de spec del proyecto.

## Editar contenido sin tocar código

| Qué cambiar | Archivo |
| --- | --- |
| Correo, WhatsApp, tiempo de respuesta, LinkedIn del equipo, destino del formulario | `src/data/contacto.json` |
| Todos los textos de la página | `src/data/contenido.json` |
| Texto alternativo y anchos de las imágenes | `src/data/imagenes.js` |

Un valor vacío (`""`) o `null` oculta su botón, fila o enlace. Cada cambio en `main` se publica solo en GitHub Pages.

### Formulario

`formularioEndpoint` en `contacto.json` acepta:

- vacío: el formulario se muestra como vista previa y no envía nada;
- una URL de Web3Forms (`https://api.web3forms.com/submit`) más `formularioClave` con la access key: funciona en GitHub Pages;
- `netlify`: solo cuando el sitio se aloje en Netlify.

## Desarrollo local

```bash
npm install
npm run dev      # http://localhost:4321
npm run build    # genera dist/
```

## Estructura

```text
src/data/          contenido editable (JSON)
src/components/    una sección por archivo
src/styles/        tokens.css (colores, tipografía, espacios) y base.css
public/img/        fotos (AVIF/WebP) y vistas CAD
```
