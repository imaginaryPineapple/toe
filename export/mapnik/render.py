#!/usr/bin/env python
# coding=utf8

# run this in mapnik stylesheet directory!
# Example:
# cd ~/mapnik-stylesheets
# echo '{"areas":[],"pois":[]}' | ../www/toe/export/mapnik/render.py -b "((61.477925877956785, 21.768811679687474), (61.488948601502614, 21.823743320312474))" -s 144x93

import sys, os
import mapnik2
import cairo
import json
import argparse
import tempfile
from globalmaptiles import GlobalMercator
from tileloader import GoogleTileLoader, TMSTileLoader, FTileLoader

#sys.stdout.write("areas: '" + str(areas) + "'\n")
#sys.stdout.write("pois: '" + str(areas) + "'\n")
#sys.exit(0)


# ensure minimum mapnik version
if not hasattr(mapnik2,'mapnik_version') and not mapnik2.mapnik_version() >= 600:
    raise SystemExit('This script requires Mapnik >=0.6.0)')

# Google bounds toString() gives following string:
# ((61.477925877956785, 21.768811679687474), (61.488948601502614, 21.823743320312474))
def googleBoundsToBox2d(google_bounds):
    parts = google_bounds.split(",")
    strip_str = "() "
    min_lat = float(parts[0].strip(strip_str))
    min_lng = float(parts[1].strip(strip_str))
    max_lat = float(parts[2].strip(strip_str))
    max_lng = float(parts[3].strip(strip_str))
    return (min_lng, min_lat, max_lng, max_lat)

class StyleParser:
    DEFAULT_STYLE="default"
    UNIT="unit"
    UNIT_CM="cm"
    UNIT_MM="mm"
    UNIT_PX="px"
    UNIT_INCH="in"
    DEFAULT_UNIT=UNIT_PX

    def __init__(self, style_file, style_name):
        styles_file = os.path.join(sys.path[0], style_file)
        f = open(styles_file, 'r')
        data = f.read()
        f.close()
        obj = json.loads(data)
        self.style = obj[style_name or self.DEFAULT_STYLE]

    def get(self, key, default=None):
        return self.style.get(key, default)

    def get_px(self, key, default=None):
        value = self.get(key, default)
        if isinstance(value, list):
            # convert list values
            li = list()
            for v in value:
                li.append(self.to_px(v))
            value = li
        else:
            # convert value
            value = self.to_px(value)
        return value

    def to_px(self, value):
        """Returns value in px and converts units automatically.
           Unit may be told with 'unit' key in styles.json."""
        unit = self.get(self.UNIT, self.DEFAULT_UNIT)
        if unit == self.UNIT_PX:
            return value
        elif unit == self.UNIT_CM:
            return self._cm_to_px(value)
        elif unit == self.UNIT_MM:
            return self._mm_to_px(value)
        elif unit == self.UNIT_INCH:
            return self._inch_to_px(value)

    def _cm_to_px(self, v):
        return int(v * 72 / 2.54)

    def _mm_to_px(self, v):
        return int(v * 72 / 25.4)

    def _inch_to_px(self, v):
        return int(v * 72)

    def _get_unit(self):
        return self.get(self.UNIT, self.DEFAULT_UNIT)


class Layer(object):
    """Base class for Layer classes."""
    def __init__(self, renderer):
        self.renderer = renderer
        # for convenience
        self.ctx = renderer.get_context()
        self.m = renderer.get_map()
        self.style = renderer.get_style()

    def draw(self):
        """Implement this in subclasses."""
        pass

    def _convert_point(self, latlng):
        """Converts given latlng to XY coordinates."""
        coord = self._google_to_mapnik_coord(latlng)
        merc_coord = self.renderer.get_transform().forward(coord)
        view_coord = self.m.view_transform().forward(merc_coord)
        return view_coord

    # Google Maps uses LatLng, Mapnik uses LngLat!
    def _google_to_mapnik_coord(self, latlng):
        coord = mapnik2.Coord(latlng[1], latlng[0])
        return coord

class MapnikLayer(Layer):
    """Layer for Mapnik map."""
    def draw(self):
        mapnik2.render(self.m, self.ctx)

class AreaLayer(Layer):
    """Layer for area borders."""
    def __init__(self, renderer, areas):
        super(AreaLayer, self).__init__(renderer)
        self.areas = areas

    def draw(self):
        # save context before zoom so we can restore it later
        self.ctx.save()

        # apply zoom
        zoom = self.renderer.get_zoom()
        self.ctx.scale(zoom, zoom)

        for area in self.areas:
            self._draw_area(area)

        # set brush color and line width
        self.ctx.set_source_rgba(self.style.get('area_border_color')[0],
                                  self.style.get('area_border_color')[1],
                                  self.style.get('area_border_color')[2],
                                  self.style.get('area_border_color')[3])
        self.ctx.set_line_width(self.style.get('area_border_width'))
        self.ctx.stroke()

        #self.ctx.scale(self.zoom_f, self.zoom_f)
        self.ctx.restore()

    def _draw_area(self, area):


        coords = list()
        for coord in area['path']:
            coords.append(self._convert_point(coord))
        if len(coords) < 2:
            pass # area has only one point?

        start = coords.pop()
        self.ctx.move_to(start.x, start.y)
        while len(coords):
            coord = coords.pop()
            self.ctx.line_to(coord.x, coord.y)
        self.ctx.close_path()


class CopyrightLayer(Layer):
    def __init__(self, renderer, text):
        super(CopyrightLayer, self).__init__(renderer)
        self.text = text

    def draw(self):
        self.ctx.save()
        zoom = 1
        self.ctx.scale(zoom, zoom)
        self.ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_NORMAL)
        self.ctx.set_font_size(6)
        margin = self.style.get_px('copyright_margin', [ 3, 3 ])
        map_size = self.renderer.get_map_size()
        x = margin[0]
        y = map_size[1] - margin[1]
        self.ctx.move_to(x, y)
        self.ctx.show_text(self.text)
        self.ctx.restore()

class QRCodeLayer(Layer):
    def __init__(self, renderer, qrcode_file):
        super(QRCodeLayer, self).__init__(renderer)
        self.qrcode_file = qrcode_file

    def draw(self):
        self.ctx.save()
        zoom = 0.3
        self.ctx.scale(zoom, zoom)
        img = cairo.ImageSurface.create_from_png(self.qrcode_file)
        margin = self.style.get_px('qrcode_margin', [ 0, 0 ])
        map_size = self.renderer.get_map_size()
        x = int(1 / zoom * map_size[0]) - img.get_width() - margin[0]
        y = int(1 / zoom * map_size[1]) - img.get_height() - margin[1]
        self.ctx.set_source_surface(img, x, y)
        self.ctx.paint()
        self.ctx.restore()

class CustomMapLayer(Layer):
    def __init__(self, renderer, cache_dir, bounds):
        super(CustomMapLayer, self).__init__(renderer)
        self.cache_dir = cache_dir
        self.mercator = GlobalMercator()
        self.tileloader = None
        if self.style.get('map_tiles') is not None:
            self.options = self.style.get('map_tiles')
            min_lon = float(bounds[0])
            min_lat = float(bounds[1])
            max_lon = float(bounds[2])
            max_lat = float(bounds[3])
            width = 512
            if self.options['indexing'] == 'google':
                self.tileloader = GoogleTileLoader(min_lat, min_lon, max_lat, max_lon, width)
            elif self.options['indexing'] == 'tms':
                self.tileloader = TMSTileLoader(min_lat, min_lon, max_lat, max_lon, width)
            elif self.options['indexing'] == 'f':
                self.tileloader = FTileLoader(min_lat, min_lon, max_lat, max_lon, width)

    def draw(self):
        if self.tileloader is not None:
            for tile in self._get_tiles():
                tile.draw()

    def _get_tiles(self):
        tiles = list()
        tile_files = self.tileloader.download(self.cache_dir, self.options['url'], self.options['http_headers'])
        for filename in tile_files:
            print "TILE: " + filename
            tile = TileLayer(self.renderer, filename, self.mercator)
            tiles.append(tile)
        return tiles

class TileLayer(Layer):
    """Used by CustomMapLayer."""

    def __init__(self, renderer, filename, mercator):
        super(TileLayer, self).__init__(renderer)
        self.filename = filename
        self.mercator = mercator
        basename = os.path.basename(filename).split('.')[0]
        parts = basename.split('_')
        # XYZ is part of the tile filename
        self.tx = 0
        self.ty = 0
        self.tz = 0
        if (len(parts) == 3):
            self.tx, self.ty, self.tz = int(parts[0]), int(parts[1]), int(parts[2])

    def draw(self):
        (min_lat, min_lon, max_lat, max_lon) = self.mercator.TileLatLonBounds(self.tx, self.ty, self.tz)
        #print min_lat, min_lon, max_lat, max_lon
        coord_nw = self._convert_point([max_lat, min_lon])
        coord_se = self._convert_point([min_lat, max_lon])

        #self.ctx.move_to(coord_nw.x, coord_nw.y)
        #self.ctx.line_to(coord_se.x, coord_se.y)

        #print str(coord)
        #print str(coord2)
        tile_width = coord_se.x - coord_nw.x
        #tile_file = '/home/tumppi/www/toe/export/mapnik/tilecache/14_9183_11764.png'
        self.ctx.save()
        #self.ctx.move_to(coord_nw.x, coord_nw.y)
        # assume it is png
        img = cairo.ImageSurface.create_from_png(self.filename)
        zoom = tile_width / 256
        #zoom = 0.26
        #zoom = 0.3
        self.ctx.scale(zoom, zoom)
        #print "sizes: ", str(img.get_width()), tile_slot_width
        self.ctx.set_source_surface(img, int(1 / zoom * coord_nw.x), int(1 / zoom * coord_nw.y))
        self.ctx.paint()
        self.ctx.restore()


class MapnikRenderer:

    STYLES_FILE="styles.json"
    COPYRIGHT_TEXT="© OpenStreetMap contributors, CC-BY-SA"
    TILE_CACHE_DIR="/tmp/tilecache"

    def __init__(self, areas):
        self.areas = areas
        self.style = None

    def render(self, style_name, qrcode):
        self.style = StyleParser(self.STYLES_FILE, style_name)

        try:
            mapfile = os.environ['MAPNIK_MAP_FILE']
        except KeyError:
            mapfile = "osm.xml"

        (tmp_file_handler, tmp_file) = tempfile.mkstemp()
        map_uri = tmp_file

        bounds = googleBoundsToBox2d(args.bbox)
        if hasattr(mapnik2,'Box2d'):
            bbox = mapnik2.Box2d(*bounds)
        else:
            bbox = mapnik2.Envelope(*bounds)

        # Set up projections
        # spherical mercator (most common target map projection of osm data imported with osm2pgsql)
        merc = mapnik2.Projection('+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null +no_defs +over')

        # long/lat in degrees, aka ESPG:4326 and "WGS 84"
        longlat = mapnik2.Projection('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')
        # can also be constructed as:
        #longlat = mapnik.Projection('+init=epsg:4326')

        # Our bounds above are in long/lat, but our map
        # is in spherical mercator, so we need to transform
        # the bounding box to mercator to properly position
        # the Map when we call `zoom_to_box()`
        self.transform = mapnik2.ProjTransform(longlat,merc)
        self.merc_bbox = self.transform.forward(bbox)

        # auto switch paper and map orientation
        # default orientation in styles is landscape
        self._get_sizes()

        # Create the map
        self.zoom = self.style.get('zoom')
        self.zoom_f = 1 / self.zoom # zoom factor

        self.m = mapnik2.Map(int(self.zoom_f * self.map_size[0]),
                              int(self.zoom_f * self.map_size[1]))
        mapnik2.load_map(self.m, mapfile)

        # ensure the target map projection is mercator
        self.m.srs = merc.params()

        # Mapnik internally will fix the aspect ratio of the bounding box
        # to match the aspect ratio of the target image width and height
        # This behavior is controlled by setting the `m.aspect_fix_mode`
        # and defaults to GROW_BBOX, but you can also change it to alter
        # the target image size by setting aspect_fix_mode to GROW_CANVAS
        #m.aspect_fix_mode = mapnik.GROW_CANVAS
        # Note: aspect_fix_mode is only available in Mapnik >= 0.6.0
        self.m.zoom_to_box(self.merc_bbox)

        # get output format from styles.json, default is pdf
        output_format = self.style.get('format', 'pdf')

        # we will render the map to cairo surface
        surface = None
        if output_format == 'pdf':
            surface = cairo.PDFSurface(map_uri, self.paper_size[0], self.paper_size[1])
        elif output_format == 'svg':
            surface = cairo.SVGSurface(map_uri, self.m.width, self.m.height)
        self.ctx = cairo.Context(surface)

        # margins
        margin = self.style.get_px('margin')
        self.ctx.translate(margin[0],
                            margin[1])

        # create layers
        layers = list()
        layers.append(MapnikLayer(self))
        layers.append(CustomMapLayer(self, self.TILE_CACHE_DIR, bounds))
        layers.append(AreaLayer(self, self.areas))
        layers.append(CopyrightLayer(self, self.COPYRIGHT_TEXT))

        if qrcode and self.style.get('qrcode', True):
            layers.append(QRCodeLayer(qrcode))

        # draw layers
        for layer in layers:
            layer.draw()

        surface.finish()
        self.output_file = map_uri

    """
    Parses STYLES_FILE json file and saves data to self.style.
    """
    #def _parse_styles_file(self, style_name):
    #    styles_file = os.path.join(sys.path[0], self.STYLES_FILE)
    #    f = open(styles_file, 'r')
    #    data = f.read()
    #    f.close()
    #    obj = json.loads(data)
    #    self.style = obj[style_name]

    def get_map(self):
        return self.m

    def get_context(self):
        return self.ctx

    def get_transform(self):
        return self.transform

    def get_style(self):
        return self.style

    def get_map_size(self):
        return self.map_size

    def get_paper_size(self):
        return self.paper_size

    def get_mercator(self):
        return self.mercator

    def get_zoom(self):
        return self.zoom

    #def _print_qr_code(self, qrcode):
        #self.ctx.save()
        #zoom = 0.3
        #self.ctx.scale(zoom, zoom)
        #img = cairo.ImageSurface.create_from_png(qrcode)
        #margin = self.style.get_px('qrcode_margin', [ 0, 0 ])
        #x = int(1 / zoom * self.map_size[0]) - img.get_width() - margin[0]
        #y = int(1 / zoom * self.map_size[1]) - img.get_height() - margin[1]
        #self.ctx.set_source_surface(img, x, y)
        #self.ctx.paint()
        #self.ctx.restore()

    def _get_sizes(self):
        self.paper_size = self.style.get_px('paper_size')
        self.map_size = self.style.get_px('map_size')
        if self.style.get('orientation') == 'auto' and self.merc_bbox.width() / self.merc_bbox.height() < 1:
            # change orientation
            self.paper_size.reverse()
            self.map_size.reverse()

    def get_output(self):
        return self.output_file

    #def _draw_tile(self):
        #mercator = GlobalMercator()
        #tx = 9183
        #ty = 11764
        #tz = 14
        #(min_lat, min_lon, max_lat, max_lon) = mercator.TileLatLonBounds(tx, ty, tz)
        ##print min_lat, min_lon, max_lat, max_lon
        #coord = self._convert_point([max_lat, min_lon])
        #coord2 = self._convert_point([min_lat, max_lon])

        #self.ctx.move_to(coord.x, coord.y)
        #self.ctx.line_to(coord2.x, coord2.y)

        #print str(coord)
        #print str(coord2)
        #tile_slot_width = coord2.x - coord.x
        #tile_file = '/home/tumppi/www/toe/export/mapnik/tilecache/14_9183_11764.png'
        #self.ctx.save()
        #self.ctx.move_to(coord.x, coord.y)
        #img = cairo.ImageSurface.create_from_png(tile_file)
        #zoom = tile_slot_width / 256
        ##zoom = 0.26
        ##zoom = 0.3
        #self.ctx.scale(zoom, zoom)
        #print "sizes: ", str(img.get_width()), tile_slot_width
        #margin = self.style.get_px('qrcode_margin', [ 0, 0 ])
        #x = int(1 / zoom * self.map_size[0]) - img.get_width() - margin[0]
        #y = int(1 / zoom * self.map_size[1]) - img.get_height() - margin[1]
        #self.ctx.set_source_surface(img, int(1 / zoom * coord.x), int(1 / zoom * coord.y))
        #self.ctx.paint()
        #self.ctx.restore()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Mapnik renderer.')
    parser.add_argument('-b', '--bbox', required=True)
    parser.add_argument('-s', '--style', required=False, default=None)
    parser.add_argument('-q', '--qrcode', required=False, default=None)
    args = parser.parse_args()

    #sys.stdout.write("'" + str(args.bbox) + "'\n")

    stdin_data = sys.stdin.read()
    data = json.loads(stdin_data)
    areas = data['areas']
    pois = data['pois']

    r = MapnikRenderer(areas)
    r.render(args.style, args.qrcode)
    fn = r.get_output()
    sys.stdout.write("%s" % fn)

    #m = mapnik.Map(imgx,imgy)
    #mapnik.load_map(m,mapfile)
