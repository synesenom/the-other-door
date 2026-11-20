---
name: stylist-cv-request
description: Not for direct use — do not invoke it from a conversation; `door.style.style_build` sends this as the user message of a CV round to the stylist, filling in the page count, the fonts, icons, columns, page limit and page size.
---

Rebuild the look of the CV in this folder as a template. Files here: original_page_1.png to original_page_{pages}.png (the CV; look at them with the Read tool), style.json, text.txt, fonts.css, template.json. Your last template, when there is one, is cv.template.html and the print of the last one that printed is render_page_1.png and on (render_page_N.png for the other pages).
Fonts (use only these; the @font-face rules are in fonts.css):
{fonts}
Icons you may draw, by kind: {icons}.
Side column: {columns}. Page limit: {max_pages}. Page size: {page_size}, set it with @page size.
