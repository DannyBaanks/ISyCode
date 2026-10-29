"""Rasterize Textual's original SVG with the host's librsvg, offline."""
import sys
import xml.etree.ElementTree as ET
import ctypes as C

path, output = sys.argv[1:]
_, _, width, height = map(float, ET.parse(path).getroot().attrib['viewBox'].split())
class Rectangle(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double), ('width', C.c_double), ('height', C.c_double)]

cairo = C.CDLL('libcairo.so.2')
rsvg = C.CDLL('librsvg-2.so.2')
cairo.cairo_image_surface_create.argtypes = [C.c_int, C.c_int, C.c_int]
cairo.cairo_image_surface_create.restype = C.c_void_p
cairo.cairo_create.argtypes = [C.c_void_p]
cairo.cairo_create.restype = C.c_void_p
rsvg.rsvg_handle_new_from_file.argtypes = [C.c_char_p, C.c_void_p]
rsvg.rsvg_handle_new_from_file.restype = C.c_void_p
rsvg.rsvg_handle_render_document.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(Rectangle), C.c_void_p]
rsvg.rsvg_handle_render_document.restype = C.c_int
cairo.cairo_surface_write_to_png.argtypes = [C.c_void_p, C.c_char_p]
cairo.cairo_surface_write_to_png.restype = C.c_int
surface = cairo.cairo_image_surface_create(0, int(width), int(height))
context = cairo.cairo_create(surface)
handle = rsvg.rsvg_handle_new_from_file(path.encode(), None)
assert handle and rsvg.rsvg_handle_render_document(handle, context, C.byref(Rectangle(0, 0, width, height)), None)
assert cairo.cairo_surface_write_to_png(surface, output.encode()) == 0
