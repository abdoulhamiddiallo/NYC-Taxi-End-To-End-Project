# Dependency-free zone centroids: reads the TLC taxi_zones shapefile (ESRI .shp/.dbf inside the zip) with the
# standard library only and projects the centroids from EPSG:2263 (NAD83 / New York Long Island, US survey feet)
# to WGS84 latitude/longitude with the Lambert Conformal Conic (2SP) inverse formulas (EPSG guidance note 7-2).
# The Fabric Spark runtime ships without geopandas/pyproj, so this keeps the pipeline free of inline pip installs.
import io, math, struct, zipfile

# ---- EPSG:2263 parameters (NAD83 / New York Long Island (ftUS)) ----
_A, _F = 6378137.0, 1 / 298.257222101          # GRS80 ellipsoid
_E = math.sqrt(2 * _F - _F * _F)
_LAT1, _LAT2, _LAT0, _LON0 = map(math.radians, (40.66666666666666, 41.03333333333333, 40.16666666666666, -74.0))
_FT_US = 0.3048006096012192                    # metres per US survey foot
_FE, _FN = 300000.0, 0.0                       # false easting/northing in metres

def _m(lat): return math.cos(lat) / math.sqrt(1 - (_E * math.sin(lat)) ** 2)
def _t(lat): return math.tan(math.pi / 4 - lat / 2) / ((1 - _E * math.sin(lat)) / (1 + _E * math.sin(lat))) ** (_E / 2)
_N = (math.log(_m(_LAT1)) - math.log(_m(_LAT2))) / (math.log(_t(_LAT1)) - math.log(_t(_LAT2)))
_FF = _m(_LAT1) / (_N * _t(_LAT1) ** _N)
_R0 = _A * _FF * _t(_LAT0) ** _N

def to_wgs84(x_ft, y_ft):
    """EPSG:2263 easting/northing in US survey feet -> (latitude, longitude) in decimal degrees."""
    x = x_ft * _FT_US - _FE
    y = y_ft * _FT_US - _FN
    r = math.copysign(math.sqrt(x * x + (_R0 - y) ** 2), _N)
    t = (r / (_A * _FF)) ** (1 / _N)
    theta = math.atan2(x, _R0 - y)
    lon = theta / _N + _LON0
    lat = math.pi / 2 - 2 * math.atan(t)
    for _ in range(8):                         # fixed-point iteration converges in a handful of steps
        lat = math.pi / 2 - 2 * math.atan(t * ((1 - _E * math.sin(lat)) / (1 + _E * math.sin(lat))) ** (_E / 2))
    return math.degrees(lat), math.degrees(lon)

def _ring_area_centroid(pts):
    """Signed area and centroid of a closed ring (shoelace formula)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cross = x0 * y1 - x1 * y0
        a += cross; cx += (x0 + x1) * cross; cy += (y0 + y1) * cross
    if a == 0: return 0.0, 0.0, 0.0
    return a / 2, cx / (3 * a), cy / (3 * a)

def read_shapefile(shp_bytes):
    """Yields (record_index, [(area, cx, cy) per ring]) for every polygon record of an ESRI .shp file."""
    pos, n = 100, len(shp_bytes)                 # 100-byte file header
    idx = 0
    while pos < n:
        content_len = struct.unpack(">i", shp_bytes[pos + 4:pos + 8])[0] * 2
        rec = shp_bytes[pos + 8:pos + 8 + content_len]
        shape_type = struct.unpack("<i", rec[:4])[0]
        rings = []
        if shape_type in (5, 15, 25):            # Polygon, PolygonZ, PolygonM
            num_parts, num_points = struct.unpack("<ii", rec[36:44])
            parts = struct.unpack(f"<{num_parts}i", rec[44:44 + 4 * num_parts])
            base = 44 + 4 * num_parts
            pts = struct.unpack(f"<{2 * num_points}d", rec[base:base + 16 * num_points])
            xy = list(zip(pts[0::2], pts[1::2]))
            for i, start in enumerate(parts):
                end = parts[i + 1] if i + 1 < num_parts else num_points
                rings.append(_ring_area_centroid(xy[start:end]))
        yield idx, rings
        idx += 1
        pos += 8 + content_len

def read_dbf_column(dbf_bytes, name):
    """Returns the values of one column of an ESRI .dbf file (as stripped strings)."""
    n_rec, hdr_len, rec_len = struct.unpack("<IHH", dbf_bytes[4:12])
    fields, off = [], 32
    while dbf_bytes[off] != 0x0D:
        fname = dbf_bytes[off:off + 11].split(b"\x00")[0].decode("latin-1")
        flen = dbf_bytes[off + 16]
        fields.append((fname, flen)); off += 32
    start = 1                                    # first byte of each record is the deletion flag
    for fname, flen in fields:
        if fname.upper() == name.upper(): break
        start += flen
    else:
        raise KeyError(name)
    return [dbf_bytes[hdr_len + i * rec_len + start: hdr_len + i * rec_len + start + flen].decode("latin-1").strip()
            for i in range(n_rec)]

def zone_centroids(zip_path):
    """{location_id: (latitude, longitude, area_sq_mi)} from the TLC taxi_zones.zip (multi-part zones are area weighted)."""
    with zipfile.ZipFile(zip_path) as z:
        shp = next(n for n in z.namelist() if n.lower().endswith(".shp"))
        dbf = next(n for n in z.namelist() if n.lower().endswith(".dbf"))
        shp_bytes, dbf_bytes = z.read(shp), z.read(dbf)
    ids = read_dbf_column(dbf_bytes, "LocationID")
    out = {}
    for idx, rings in read_shapefile(shp_bytes):
        # outer rings have positive signed area (clockwise in shapefiles gives negative), holes the opposite sign;
        # summing signed contributions gives the net area and the area weighted centroid of the polygon
        area = sum(a for a, _, _ in rings)
        if area == 0: continue
        cx = sum(a * x for a, x, _ in rings) / area
        cy = sum(a * y for a, _, y in rings) / area
        lat, lon = to_wgs84(cx, cy)
        loc = int(ids[idx])
        sq_mi = abs(area) / 27_878_400.0          # square US survey feet per square mile
        if loc in out:                            # a zone split into several records: weight by area
            la, lo, ar = out[loc]
            out[loc] = ((la * ar + lat * sq_mi) / (ar + sq_mi), (lo * ar + lon * sq_mi) / (ar + sq_mi), ar + sq_mi)
        else:
            out[loc] = (lat, lon, sq_mi)
    return {k: (round(v[0], 6), round(v[1], 6), round(v[2], 4)) for k, v in out.items()}
