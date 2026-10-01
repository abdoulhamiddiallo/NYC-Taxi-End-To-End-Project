# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # NB_03 · Deploy the Power BI report as code (PBIR)
#
# **Role**: Semantic model ➜ **Report**. The whole report (pages, visuals, theme, filters) is generated from Python
# and pushed to the workspace through the Fabric REST API (`reports` endpoint, PBIR definition format).
#
# Why generate the report instead of clicking it together?
#
# * **Reproducible**: the report is rebuilt identically in any workspace (dev, test, prod) from one script.
# * **Reviewable**: layout, measures and colours live in code and can be diffed and versioned.
# * **Consistent**: every visual inherits the same theme (NYC Taxi Night), fonts, paddings and number formats.
#
# Parameters: `report_name` (target item), `semantic_model_name` (Direct Lake model to bind), `pages` ("all" or a comma separated
# subset such as "overview,demand" for a quick preview build).

# PARAMETERS CELL ********************

report_name = "RPT_NYC_Taxi"
semantic_model_name = "SM_NYC_Taxi"
pages = "all"

# CELL ********************

import base64, hashlib, json, time
import sempy.fabric as fabric

W, H = 1600, 900
KPI_H = 116

# ------------------------------------------------------------------ palette
BG, PANEL, PANEL2, LINE = "#0B0F19", "#141A26", "#1B2333", "#27314A"
INK, MUTED, DIM = "#F2F5FA", "#A7B1C6", "#6F7A93"
NAVY = "#1B2333"          # value ink on the white visual panels (INK is kept for text on the dark page)
YEL, CYAN, CORAL, GREEN, VIOLET, ORANGE = "#F5C518", "#4CC9F0", "#FF6B6B", "#3DDC97", "#B084F5", "#FF9F43"
FONT = "Segoe UI"

def hid(*parts): return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]
def lit(v):
    if isinstance(v, bool): return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)): return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}
def color(c): return {"solid": {"color": lit(c)}}
def ent(t): return {"Expression": {"SourceRef": {"Entity": t}}}
def col(t, c): return {"Column": {**ent(t), "Property": c}}
def mea(t, c): return {"Measure": {**ent(t), "Property": c}}
def proj(field, qref, **kw): return {"field": field, "queryRef": qref, **kw}

def M(name, label=None):
    p = proj(mea("Trips", name), f"Trips.{name}")
    if label: p["displayName"] = label
    return p
def C(t, c, label=None):
    p = proj(col(t, c), f"{t}.{c}")
    if label: p["displayName"] = label
    return p
def AGG(t, c, fn=1): return proj({"Aggregation": {"Expression": col(t, c), "Function": fn}}, f"{fn}({t}.{c})")

# ------------------------------------------------------------------ visual factory
class Page:
    def __init__(self, name, display, ordinal):
        self.name, self.display, self.ordinal = name, display, ordinal
        self.visuals = []
        self.z = 0

    def add(self, vtype, x, y, w, h, roles=None, title=None, subtitle=None, objects=None, vco=None,
            sort=None, filters=None, extra=None, bg=True, name=None):
        self.z += 1
        v = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
             "name": name or hid(self.name, vtype, str(x), str(y), title or "", str(self.z)),
             "position": {"x": x, "y": y, "z": self.z * 100, "height": h, "width": w},
             "visual": {"visualType": vtype}}
        if roles:
            v["visual"]["query"] = {"queryState": {r: {"projections": p} for r, p in roles.items()}}
            if sort: v["visual"]["query"]["sortDefinition"] = {"sort": sort, "isDefaultSort": True}
        if objects: v["visual"]["objects"] = objects
        vc = {}
        if title is not None:
            vc["title"] = [{"properties": {"show": lit(True), "text": lit(title)}}]
            if subtitle:
                vc["subTitle"] = [{"properties": {"show": lit(True), "text": lit(subtitle)}}]
        else:
            vc["title"] = [{"properties": {"show": lit(False)}}]
        if not bg:
            vc["background"] = [{"properties": {"show": lit(False)}}]
            vc["border"] = [{"properties": {"show": lit(False)}}]
        if vco: vc.update(vco)
        v["visual"]["visualContainerObjects"] = vc
        if extra: v["visual"].update(extra)
        if filters: v["filterConfig"] = {"filters": filters}
        self.visuals.append(v)
        return v

    def text(self, x, y, w, h, runs, align="left"):
        """runs: list of (text, size_pt, color, bold)"""
        paras = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{s}pt", "color": c, **({"fontWeight": "bold"} if b else {})}}],
                  "horizontalTextAlignment": align} for (t, s, c, b) in runs]
        return self.add("textbox", x, y, w, h, objects={"general": [{"properties": {"paragraphs": paras}}]}, bg=False)

    def card(self, x, y, w, h, measure, label, size=30, ink=NAVY, entity="Trips", units=1):
        f = M(measure) if entity == "Trips" else proj(mea(entity, measure), f"{entity}.{measure}")
        props = {"fontSize": lit(size), "color": color(ink), "labelDisplayUnits": lit(units)}
        if units >= 1000:                                   # fixed units (millions): show whole millions, e.g. $1,310M
            props["labelPrecision"] = {"expr": {"Literal": {"Value": "0L"}}}
        obj = {"labels": [{"properties": props}], "categoryLabels": [{"properties": {"show": lit(False)}}]}
        return self.add("card", x, y, w, h, roles={"Values": [f]}, title=label, objects=obj)

    def context(self, x, y, w, h, measure, ink=MUTED, size=10):
        obj = {"labels": [{"properties": {"fontSize": lit(size), "color": color(ink)}}],
               "categoryLabels": [{"properties": {"show": lit(False)}}]}
        return self.add("card", x, y, w, h, roles={"Values": [M(measure)]}, objects=obj, bg=False)

    def kpi(self, x, y, w, measure, label, ctx, size=28, ink=NAVY, units=1):
        """Panel: title label on top, big value in the middle, context sentence in muted text at the bottom."""
        self.card(x, y, w, KPI_H, measure, label, size, ink, units=units)
        self.context(x + 6, y + KPI_H - 26, w - 12, 22, ctx)

    def slicer(self, x, y, w, h, t, c, horizontal=True, label=None):
        obj = {"general": [{"properties": {"orientation": lit(1 if horizontal else 0)}}],
               "header": [{"properties": {"show": lit(False)}}]}
        return self.add("slicer", x, y, w, h, roles={"Values": [C(t, c)]}, objects=obj, bg=False)

# ------------------------------------------------------------------ common formatting fragments
def axes(units=1, val_show=True):
    """Axis titles are hidden: the subtitle of each visual names what is plotted, so no technical field name reaches the reader."""
    return {"valueAxis": [{"properties": {"show": lit(val_show), "labelDisplayUnits": lit(units), "showAxisTitle": lit(False)}}],
            "categoryAxis": [{"properties": {"showAxisTitle": lit(False)}}]}
def bar_axes(margin=40):
    """Horizontal bars with data labels: no value axis, and a wider category margin so long zone names are not cut."""
    return {"valueAxis": [{"properties": {"show": lit(False), "showAxisTitle": lit(False)}}],
            "categoryAxis": [{"properties": {"showAxisTitle": lit(False), "maxMarginFactor": {"expr": {"Literal": {"Value": f"{margin}L"}}}}}]}
def combo_axis(sec_color):
    return {"valueAxis": [{"properties": {"labelDisplayUnits": lit(0), "showAxisTitle": lit(False), "secShow": lit(True),
                                          "secLabelColor": color(sec_color), "secShowAxisTitle": lit(False)}}]}
def legend(show=True, pos="Top"): return {"legend": [{"properties": {"show": lit(show), "position": lit(pos), "showTitle": lit(False)}}]}
def labels(show=True, size=10, units=0, c=INK): return {"labels": [{"properties": {"show": lit(show), "labelDisplayUnits": lit(units)}}]}
def fill(c): return {"dataPoint": [{"properties": {"fill": color(c)}}]}
def series_colors(pairs):
    """pairs: list of (queryRef, color) -> dataPoint entries with metadata selectors"""
    return {"dataPoint": [{"properties": {"fill": color(c)}, "selector": {"metadata": q}} for q, c in pairs]}
def table_style(size=11, hdr=11, rowpad=4, widths=None):
    o = {"grid": [{"properties": {"rowPadding": lit(rowpad), "textSize": lit(size)}}],
         "columnHeaders": [{"properties": {"fontSize": lit(hdr)}}],
         "values": [{"properties": {"fontSize": lit(size)}}]}
    if widths:
        o["columnWidth"] = [{"properties": {"value": lit(wd)}, "selector": {"metadata": q}} for q, wd in widths]
    return o
def sort_desc(field): return [{"field": field, "direction": "Descending"}]
def sort_asc(field): return [{"field": field, "direction": "Ascending"}]

def col_filter(t, c, kind, value, name="f1", suffix="L"):
    """Advanced filter on a column: kind 0 == , 1 >, 2 >=, 3 <, 4 <= ; suffix L for integers, D for decimals"""
    return {"name": name, "field": col(t, c), "type": "Advanced", "howCreated": "User",
            "filter": {"Version": 2, "From": [{"Name": "s", "Entity": t, "Type": 0}],
                       "Where": [{"Condition": {"Comparison": {"ComparisonKind": kind, "Left": {"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": c}},
                                                               "Right": {"Literal": {"Value": f"{value}{suffix}"}}}}}]}}
def mea_filter(mname, kind, value, mt="Trips", name="mf"):
    """Advanced filter on a measure of the Trips table (kind 4 == less or equal), e.g. a rank measure for a robust Top N."""
    return {"name": name, "field": mea(mt, mname), "type": "Advanced", "howCreated": "User",
            "filter": {"Version": 2, "From": [{"Name": "m", "Entity": mt, "Type": 0}],
                       "Where": [{"Condition": {"Comparison": {"ComparisonKind": kind, "Left": {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": mname}},
                                                               "Right": {"Literal": {"Value": f"{value}L"}}}}}]}}
def topn_filter(t, c, n, mt="Trips", mname="Trips", name="topn"):
    """Top N filter: the column must be in the subquery that keeps the N best values of the measure."""
    sub = {"Version": 2, "From": [{"Name": "s", "Entity": t, "Type": 0}, {"Name": "m", "Entity": mt, "Type": 0}],
           "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": c}, "Name": f"{t}.{c}"}],
           "OrderBy": [{"Direction": 2, "Expression": {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": mname}}}],
           "Top": n}
    return {"name": name, "field": col(t, c), "type": "TopN", "howCreated": "User",
            "filter": {"Version": 2, "From": [{"Name": "s", "Entity": t, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": c}}],
                                                       "Table": {"Subquery": {"Query": sub}}}}}]}}
def cat_in_filter(t, c, values, name="cat"):
    return {"name": name, "field": col(t, c), "type": "Categorical", "howCreated": "User",
            "filter": {"Version": 2, "From": [{"Name": "s", "Entity": t, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": c}}],
                                                       "Values": [[{"Literal": {"Value": "'" + v + "'"}}] for v in values]}}}]}}

# ------------------------------------------------------------------ page chrome
def header(p, title, subtitle, slicers=True):
    p.text(24, 0, 520, 64, [(title, 26, INK, True)])
    p.text(24, 58, 1000, 40, [(subtitle, 12, MUTED, False)])
    if slicers:
        p.slicer(560, 16, 690, 46, "Date", "Mon", label=None)
        p.slicer(1262, 16, 314, 46, "Date", "Day Type")
    p.text(24, 862, 1400, 38, [("Source: NYC Taxi and Limousine Commission trip records 2025, cleansed in Microsoft Fabric (Bronze, Silver, Gold). Cash tips are not recorded by TLC.", 10, DIM, False)])

# ==================================================================== PAGE 1 : Overview
def page_overview():
    p = Page("p1overview", "Overview", 0)
    header(p, "NYC Yellow Taxi 2025", "Executive overview of 12 months of yellow cab activity across the five boroughs")
    KY, KW, GAP = 100, 248, 14
    xs = [24 + i * (KW + GAP) for i in range(6)]
    p.kpi(xs[0], KY, KW, "Trips", "TRIPS", "Trips per Day Label", ink=YEL)
    p.kpi(xs[1], KY, KW, "Revenue", "REVENUE", "Revenue per Day Label", ink=YEL, units=1000000)
    p.kpi(xs[2], KY, KW, "Avg Fare", "AVG FARE", "Avg Fare MoM Label")
    p.kpi(xs[3], KY, KW, "Avg Distance", "AVG DISTANCE (MI)", "Miles Label")
    p.kpi(xs[4], KY, KW, "Avg Duration", "AVG DURATION (MIN)", "Hours Label")
    p.kpi(xs[5], KY, KW, "Tip Rate", "CARD TIP RATE", "Tip Rate Label", ink=GREEN)
    # row 2
    p.add("lineClusteredColumnComboChart", 24, 234, 1046, 298,
          roles={"Category": [C("Date", "Month Label")], "Y": [M("Trips")], "Y2": [M("Revenue")]},
          title="Monthly trips and revenue", subtitle="Columns: trips. Line: revenue in dollars",
          objects={**axes(units=0), **legend(True, "Top"), "dataPoint": [{"properties": {"fill": color(YEL)}},
                                                                          {"properties": {"fill": color(CYAN)}, "selector": {"metadata": "Trips.Revenue"}}],
                   **combo_axis(CYAN)})
    # a sorted bar chart reads a 86 % / 9 % / 3 % split better than a donut, whose small slices overlap their labels
    p.add("clusteredBarChart", 1084, 234, 492, 298, roles={"Category": [C("Pickup Zone", "Pickup Borough")], "Y": [M("Trips Share", "Share of pickups")]},
          title="Where trips start", subtitle="Share of pickups by borough",
          objects={**bar_axes(30), **legend(False), **labels(True, 10, 0, MUTED), **fill(YEL)},
          sort=sort_desc(mea("Trips", "Trips Share")))
    # row 3
    p.add("clusteredColumnChart", 24, 546, 516, 310, roles={"Category": [C("Date", "Day Short")], "Y": [M("Trips per Day")]},
          title="Trips per day by weekday", subtitle="Average daily pickups, Monday to Sunday",
          objects={**axes(units=0), **legend(False), **labels(True, 10, 0, MUTED), **fill(CYAN)})
    p.add("barChart", 554, 546, 516, 310, roles={"Category": [C("Pickup Zone", "Pickup Zone")], "Y": [M("Trips")]},
          title="Top 10 pickup zones", subtitle="Busiest zones by number of pickups",
          objects={**bar_axes(45), **legend(False), **labels(True, 10, 0, MUTED), **fill(YEL)},
          sort=sort_desc(mea("Trips", "Trips")), filters=[mea_filter("Pickup Zone Rank", 4, 10)])
    p.add("clusteredColumnChart", 1084, 546, 492, 310, roles={"Category": [C("Date", "Day Type")], "Y": [M("Trips per Day", "Trips per day")]},
          title="Weekday, weekend and holiday", subtitle="Average pickups per day. The average fare stays close to $20 on all three",
          objects={**axes(units=0), **legend(False), **labels(True, 10, 0, MUTED), **fill(YEL)})
    return p

# ==================================================================== PAGE 2 : Demand
def page_demand():
    p = Page("p2demand", "Demand", 1)
    header(p, "When New York rides", "Hourly and weekly demand profile, rush hours and seasonality")
    KY, KW, GAP = 100, 248, 14
    xs = [24 + i * (KW + GAP) for i in range(6)]
    p.kpi(xs[0], KY, KW, "Trips per Hour of Day", "TRIPS PER HOUR", "Trips per Day Label", ink=YEL)
    p.kpi(xs[1], KY, KW, "Peak Hour", "PEAK HOUR", "Peak Hour Label", ink=YEL, units=0)
    p.kpi(xs[2], KY, KW, "Rush Hour Share", "RUSH HOUR SHARE", "Rush Hour Label")
    p.kpi(xs[3], KY, KW, "Weekend Share", "WEEKEND SHARE", "Weekend Trips Label")
    p.kpi(xs[4], KY, KW, "Avg Speed", "AVG SPEED (MPH)", "Avg Duration Label")
    p.kpi(xs[5], KY, KW, "Busiest Day", "BUSIEST DAY", "Busiest Day Label", ink=GREEN, size=22)
    # heatmap matrix weekday x hour
    heat = {**table_style(9, 9, 6),
            "subTotals": [{"properties": {"rowSubtotals": lit(False), "columnSubtotals": lit(False)}}],
            "values": [{"properties": {"fontSize": lit(9)}},
                       {"properties": {"backColor": {"solid": {"color": {"expr": {"FillRule": {"Input": mea("Trips", "Trips"),
                                                                                                "FillRule": {"linearGradient2": {"min": {"color": {"Literal": {"Value": "'#FFF6D8'"}}},
                                                                                                                                 "max": {"color": {"Literal": {"Value": "'" + YEL + "'"}}},
                                                                                                                                 "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}}}}}}}}}},
                        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "Trips.Trips"}}],
            "rowHeaders": [{"properties": {"fontSize": lit(9)}}],
            # thousands with a K suffix keep the 24 hour columns inside the panel without a horizontal scrollbar
            "columnFormatting": [{"properties": {"labelDisplayUnits": lit(1000)}, "selector": {"metadata": "Trips.Trips"}}]}
    p.add("pivotTable", 24, 234, 1046, 310, roles={"Rows": [C("Date", "Day Short", "Day")], "Columns": [C("Hour", "Hour")], "Values": [M("Trips")]},
          title="Demand heatmap", subtitle="Pickups by weekday and hour of day. Deeper yellow is busier", objects=heat)
    p.add("clusteredBarChart", 1084, 234, 492, 310, roles={"Category": [C("Hour", "Day Part")], "Y": [M("Trips")]},
          title="Trips by part of day", subtitle="Pickups in six parts of the day (night is 0 to 5 h)",
          objects={**bar_axes(30), **legend(False), **labels(True, 10, 0, MUTED), **fill(VIOLET)})
    p.add("lineChart", 24, 558, 1046, 298, roles={"Category": [C("Hour", "Hour")], "Series": [C("Date", "Day Type")], "Y": [M("Trips per Day", "Trips per day")]},
          title="Hourly profile by day type", subtitle="Average pickups per day at each hour, weekday against weekend and holiday",
          objects={**axes(units=0), **legend(True, "Top"), 
                   "dataPoint": [{"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left": col("Date", "Day Type"), "Right": {"Literal": {"Value": "'" + b + "'"}}}}}]}}
                                 for b, c in [("Weekday", YEL), ("Weekend", CYAN), ("Holiday", CORAL)]]})
    p.add("clusteredColumnChart", 1084, 558, 492, 298, roles={"Category": [C("Date", "Quarter")], "Y": [M("Trips per Day", "Trips per day")]},
          title="Seasonality", subtitle="Trips per day by quarter",
          objects={**axes(units=0), **legend(False), **labels(True, 10, 0, MUTED), **fill(CYAN)})
    return p

# ==================================================================== PAGE 3 : Zones and flows
def page_zones():
    p = Page("p3zones", "Zones and Flows", 2)
    header(p, "Where New York rides", "Pickup zones, boroughs and the busiest origin to destination flows")
    KY, KW, GAP = 100, 248, 14
    xs = [24 + i * (KW + GAP) for i in range(6)]
    p.kpi(xs[0], KY, KW, "Top Pickup Zone", "TOP PICKUP ZONE", "Top Pickup Zone Label", ink=YEL, size=16)
    p.kpi(xs[1], KY, KW, "Top Dropoff Zone", "TOP DROPOFF ZONE", "Top Dropoff Zone Label", ink=YEL, size=16)
    p.kpi(xs[2], KY, KW, "Top Borough", "TOP BOROUGH", "Top Borough Label", size=20)
    p.kpi(xs[3], KY, KW, "Airport Trips", "AIRPORT TRIPS", "Airport Label", ink=CYAN)
    p.kpi(xs[4], KY, KW, "Airport Revenue", "AIRPORT REVENUE", "Airport Revenue Label", ink=CYAN, units=0)
    p.kpi(xs[5], KY, KW, "Avg Distance", "AVG DISTANCE (MI)", "Miles Label")
    # map of pickups: Azure Maps (the Bing based "map" visual is being retired), night style, theme yellow bubbles
    L = lambda n: {"expr": {"Literal": {"Value": f"{n}L"}}}          # integer literal expected by the Azure Maps layer properties
    p.add("azureMap", 24, 234, 760, 622,
          roles={"Category": [C("Pickup Zone", "Pickup Zone (Borough)")], "Y": [AGG("Pickup Zone", "Pickup Latitude")], "X": [AGG("Pickup Zone", "Pickup Longitude")], "Size": [M("Trips")]},
          title="Pickup map", subtitle="Bubble size is the number of pickups in each TLC zone",
          objects={**legend(False), "dataPoint": [{"properties": {"fill": color(YEL)}}],
                   "mapControls": [{"properties": {"defaultStyle": lit("night"), "showStylePicker": lit(False), "showNavigationControls": lit(False),
                                                   "showSelectionControl": lit(False), "zoom": lit(9.5), "centerLatitude": lit(40.7127), "centerLongitude": lit(-73.9723)}}],
                   "bubbleLayer": [{"properties": {"show": lit(True), "bubbleRadius": L(4), "minBubbleRadius": L(4), "maxRadius": L(14), "bubbleStrokeWidth": L(1),
                                                   "autoStrokeColor": lit(True), "fillColor": color(YEL)}}]},
          filters=[col_filter("Pickup Zone", "Pickup Latitude", 1, 30, "lat", "D")])
    # top flows table
    tw = [("Pickup Zone.Pickup Zone", 210), ("Dropoff Zone.Dropoff Zone", 210), ("Zone Flow.Flow Trips", 100), ("Zone Flow.Flow Avg Fare", 100), ("Zone Flow.Flow Avg Duration", 110)]
    p.add("tableEx", 798, 234, 778, 310,
          roles={"Values": [C("Pickup Zone", "Pickup Zone", "Pickup zone"), C("Dropoff Zone", "Dropoff Zone", "Dropoff zone"), C("Zone Flow", "Flow Trips", "Trips"),
                            C("Zone Flow", "Flow Avg Fare", "Avg fare"), C("Zone Flow", "Flow Avg Duration", "Avg minutes")]},
          title="Top 8 origin to destination flows", subtitle="Trips, average fare and average duration over the year",
          objects=table_style(10, 10, 2, tw), sort=sort_desc(col("Zone Flow", "Flow Trips")), filters=[col_filter("Zone Flow", "Flow Rank", 4, 8)])
    p.add("pivotTable", 798, 558, 778, 298,
          roles={"Rows": [C("Pickup Zone", "Pickup Borough", "Pickup borough")], "Columns": [C("Dropoff Zone", "Dropoff Borough")], "Values": [M("Trips Share", "Share of trips")]},
          title="Borough to borough", subtitle="Share of all trips from the pickup borough (rows) to the dropoff borough (columns)",
          objects={**table_style(10, 10, 2), "rowHeaders": [{"properties": {"fontSize": lit(10)}}]},
          # Unknown is kept so that rows and columns add up to 100 % of trips
          filters=[cat_in_filter("Pickup Zone", "Pickup Borough", ["Manhattan", "Queens", "Brooklyn", "Bronx", "Staten Island", "EWR", "Unknown"], "pb"),
                   cat_in_filter("Dropoff Zone", "Dropoff Borough", ["Manhattan", "Queens", "Brooklyn", "Bronx", "Staten Island", "EWR", "Unknown"], "db")])
    return p

# ==================================================================== PAGE 4 : Revenue and payments
def page_revenue():
    p = Page("p4revenue", "Revenue and Payments", 3)
    header(p, "What New York pays", "Revenue mix, payment habits, tipping and the 2025 congestion fees")
    KY, KW, GAP = 100, 248, 14
    xs = [24 + i * (KW + GAP) for i in range(6)]
    p.kpi(xs[0], KY, KW, "Revenue", "TOTAL REVENUE", "Revenue MoM Label", ink=YEL, units=1000000)
    p.kpi(xs[1], KY, KW, "Revenue per Trip", "REVENUE PER TRIP", "Fare and Tip Label")
    p.kpi(xs[2], KY, KW, "Revenue per Mile", "REVENUE PER MILE", "Miles Label")
    p.kpi(xs[3], KY, KW, "Card Share", "PAID BY CARD", "Cash Share Label", ink=CYAN)
    p.kpi(xs[4], KY, KW, "Tips", "TIPS", "Tip Rate Label", ink=GREEN, units=0)
    p.kpi(xs[5], KY, KW, "CBD Congestion Fee", "CBD CONGESTION FEE", "CBD Fee per Trip Label", ink=CORAL, units=0)
    p.add("columnChart", 24, 234, 780, 298,
          roles={"Category": [C("Date", "Month Label")], "Y": [M("Fare Revenue", "Fares"), M("Tips", "Tips"), M("Surcharges", "Surcharges and fees"), M("Tolls", "Tolls")]},
          title="Revenue mix by month", subtitle="Stacked: fares, tips, surcharges and fees, tolls",
          objects={**axes(units=0), **legend(True, "Top"), **series_colors([("Trips.Fare Revenue", YEL), ("Trips.Tips", GREEN), ("Trips.Surcharges", CORAL), ("Trips.Tolls", CYAN)])})
    p.add("clusteredBarChart", 818, 234, 370, 298, roles={"Category": [C("Payment Type", "Payment Type")], "Y": [M("Trips Share", "Share of trips")]},
          title="Payment type", subtitle="Share of trips by payment method",
          objects={**bar_axes(40), **legend(False), **labels(True, 10, 0, MUTED), **fill(CYAN)},
          sort=sort_desc(mea("Trips", "Trips Share")),
          filters=[cat_in_filter("Payment Type", "Payment Type", ["Credit card", "Flex fare", "Cash", "Dispute", "No charge", "Voided trip"], "pt")])
    # the numeric hour key on a continuous axis keeps 24 points inside a narrow panel without a horizontal scrollbar
    p.add("lineChart", 1202, 234, 374, 298, roles={"Category": [C("Hour", "hour_key")], "Y": [M("Tip Rate")]},
          title="Tip rate by hour", subtitle="Card tips as a share of card fares, hour of day 0 to 23",
          objects={**axes(units=0), **legend(False), **fill(GREEN),
                   "categoryAxis": [{"properties": {"axisType": lit("Scalar"), "showAxisTitle": lit(True), "titleText": lit("Hour of day")}}]})
    p.add("lineClusteredColumnComboChart", 24, 546, 780, 310,
          roles={"Category": [C("Distance Band", "Distance Band")], "Y": [M("Trips")], "Y2": [M("Avg Fare", "Average fare")]},
          title="Distance bands", subtitle="Columns: trips per band. Line: average fare in dollars",
          objects={**axes(units=0), **legend(True, "Top"), "dataPoint": [{"properties": {"fill": color(VIOLET)}},
                                                                          {"properties": {"fill": color(YEL)}, "selector": {"metadata": "Trips.Avg Fare"}}],
                   **combo_axis(YEL)})
    p.add("lineChart", 818, 546, 758, 310, roles={"Category": [C("Date", "Month Label")], "Y": [M("Congestion Surcharge", "Congestion surcharge"), M("CBD Congestion Fee", "CBD congestion fee"), M("Airport Fee", "Airport fee")]},
          title="Fees collected by month", subtitle="Congestion surcharge, the CBD congestion relief fee introduced on 5 January 2025, and airport fees",
          objects={**axes(units=0), **legend(True, "Top"), "lineStyles": [{"properties": {"showMarker": lit(True)}}],
                   **series_colors([("Trips.Congestion Surcharge", CYAN), ("Trips.CBD Congestion Fee", CORAL), ("Trips.Airport Fee", YEL)])})
    return p

# ==================================================================== PAGE 5 : Pipeline and quality
def page_ops():
    p = Page("p5ops", "Pipeline and Quality", 4)
    header(p, "Behind the numbers", "Data quality gate, Silver to Gold reconciliation and the run log of the Fabric pipeline", slicers=False)
    KY, KW, GAP = 100, 248, 14
    xs = [24 + i * (KW + GAP) for i in range(6)]
    def k(i, m, label, ctx, ink=NAVY, units=1, size=28):
        p.kpi(xs[i], KY, KW, m, label, ctx, size, ink, units=units)
    k(0, "DQ Rows Read", "ROWS READ FROM TLC", "Files Label", ink=YEL)
    k(1, "DQ Rows Valid", "ROWS ACCEPTED", "Accepted Label", ink=GREEN)
    k(2, "DQ Rows Rejected", "ROWS QUARANTINED", "Quarantine Label", ink=CORAL)
    k(3, "DQ Reject Rate", "REJECT RATE", "Top Rule Label", ink=CORAL)
    k(4, "DQ Duplicates", "DUPLICATES REMOVED", "Duplicates Label")
    k(5, "Months Reconciled", "MONTHS RECONCILED", "Reconciliation Label", ink=GREEN)
    # second row is 270 high on this page so that the two tables below show every row without a scrollbar
    p.add("columnChart", 24, 234, 780, 270, roles={"Category": [C("Data Quality", "DQ Month")], "Y": [M("DQ Rows Valid", "Accepted"), M("DQ Rows Rejected", "Quarantined")]},
          title="Rows accepted and quarantined by month", subtitle="Every rejected row is kept in the Silver quarantine table with its failed rules",
          objects={**axes(units=0), **legend(True, "Top"), **series_colors([("Trips.DQ Rows Valid", GREEN), ("Trips.DQ Rows Rejected", CORAL)])})
    p.add("barChart", 818, 234, 758, 270, roles={"Category": [C("Data Quality Rules", "Rule Label")], "Y": [M("DQ Rule Rows", "Rejected rows")]},
          title="Why rows are quarantined", subtitle="Rejected rows by quality rule, a row can fail several rules",
          objects={**bar_axes(40), **legend(False), **labels(True, 10, 1, MUTED), **fill(CORAL)}, sort=sort_desc(mea("Trips", "DQ Rule Rows")))
    lw = [("Load Control.Load Month Number", 70), ("Load Control.Silver Rows", 110), ("Load Control.Staged Rows", 110), ("Load Control.Fact Rows", 110), ("Load Control.Is Reconciled", 100), ("Load Control.Loaded At", 160)]
    p.add("tableEx", 24, 518, 700, 338,
          roles={"Values": [C("Load Control", "Load Month Number", "Month"), C("Load Control", "Silver Rows", "Silver rows"), C("Load Control", "Staged Rows", "Staged rows"),
                            C("Load Control", "Fact Rows", "Fact rows"), C("Load Control", "Is Reconciled", "Reconciled"), C("Load Control", "Loaded At", "Loaded at")]},
          title="Silver to Gold reconciliation", subtitle="Row counts must match at every hop, the load fails otherwise",
          objects=table_style(10, 10, 1, lw), sort=sort_asc(col("Load Control", "Load Month Number")))
    rw = [("Run Log.Step", 220), ("Run Log.Status", 110), ("Run Log.Started", 170), ("Run Log.Ended", 170), ("Run Log.Rows Affected", 120)]
    p.add("tableEx", 738, 518, 838, 338,
          roles={"Values": [C("Run Log", "Step", "Step"), C("Run Log", "Status", "Status"), C("Run Log", "Started", "Started"), C("Run Log", "Ended", "Ended"),
                            C("Run Log", "Rows Affected", "Rows affected")]},
          title="Warehouse run log", subtitle="The 10 most recent stored procedure steps",
          filters=[mea_filter("Step Recency", 4, 10, name="last10")],
          objects={**table_style(10, 10, 1, rw),
                   "values": [{"properties": {"fontSize": lit(10)}},
                              {"properties": {"fontColor": {"solid": {"color": {"expr": {"Conditional": {"Cases": [
                                  {"Condition": {"Comparison": {"ComparisonKind": 0, "Left": col("Run Log", "Status"), "Right": {"Literal": {"Value": "'FAILED'"}}}}, "Value": {"Literal": {"Value": "'" + CORAL + "'"}}},
                                  {"Condition": {"Comparison": {"ComparisonKind": 0, "Left": col("Run Log", "Status"), "Right": {"Literal": {"Value": "'SUCCEEDED'"}}}}, "Value": {"Literal": {"Value": "'" + GREEN + "'"}}}]}}}}}},
                               "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "Run Log.Status"}}]},
          sort=sort_desc(col("Run Log", "Started")))
    return p

# ==================================================================== theme
def theme():
    sol = lambda c: {"solid": {"color": c}}
    return {"name": "NYC Taxi Night", "dataColors": [YEL, CYAN, VIOLET, CORAL, GREEN, ORANGE, "#8FA3FF", "#F78FB3"],
            "background": PANEL, "foreground": INK, "tableAccent": YEL, "neutralDark": INK, "neutralLight": PANEL2,
            "textClasses": {"title": {"fontSize": 14, "fontFace": FONT + " Semibold", "color": INK}, "label": {"fontSize": 11, "fontFace": FONT, "color": MUTED},
                            "callout": {"fontSize": 30, "fontFace": FONT + " Semibold", "color": INK}, "header": {"fontSize": 12, "fontFace": FONT + " Semibold", "color": INK}},
            "visualStyles": {
                "*": {"*": {"background": [{"show": True, "color": sol(PANEL), "transparency": 0}],
                            "border": [{"show": True, "color": sol(LINE), "radius": 12, "width": 1}],
                            "title": [{"fontColor": sol(INK), "fontSize": 14, "fontFamily": FONT + " Semibold", "alignment": "left"}],
                            "subTitle": [{"fontColor": sol(MUTED), "fontSize": 11, "fontFamily": FONT}],
                            "labels": [{"color": sol(MUTED), "fontSize": 10, "fontFamily": FONT}],
                            "categoryAxis": [{"labelColor": sol(MUTED), "fontSize": 11, "fontFamily": FONT, "showAxisTitle": False, "gridlineShow": False}],
                            "valueAxis": [{"labelColor": sol(MUTED), "fontSize": 11, "fontFamily": FONT, "showAxisTitle": False, "gridlineShow": True, "gridlineColor": sol(LINE)}],
                            "legend": [{"labelColor": sol(MUTED), "fontSize": 11, "fontFamily": FONT, "showTitle": False}],
                            "visualTooltip": [{"background": sol(PANEL2), "titleFontColor": sol(INK), "valueFontColor": sol(INK)}]}},
                "card": {"*": {"labels": [{"color": sol(INK), "fontSize": 30, "fontFamily": FONT + " Semibold", "labelDisplayUnits": 1}],
                               "categoryLabels": [{"show": False}],
                               "title": [{"fontColor": sol(MUTED), "fontSize": 12, "fontFamily": FONT}]}},
                "slicer": {"*": {"items": [{"fontColor": sol(INK), "background": sol(PANEL2), "fontSize": 11, "outline": "None", "fontFamily": FONT}],
                                 "selection": [{"selectAllCheckboxEnabled": False, "singleSelect": False}],
                                 "data": [{"mode": "Basic"}]}},
                "tableEx": {"*": {"grid": [{"gridVertical": False, "gridHorizontal": True, "gridHorizontalColor": sol(LINE), "gridHorizontalWeight": 1, "outlineColor": sol(LINE)}],
                                  "columnHeaders": [{"fontColor": sol(YEL), "backColor": sol(PANEL2), "fontFamily": FONT + " Semibold", "outline": "None"}],
                                  "values": [{"fontColorPrimary": sol(INK), "backColorPrimary": sol(PANEL), "fontColorSecondary": sol(INK), "backColorSecondary": sol(PANEL2), "fontFamily": FONT}],
                                  "total": [{"totals": False}]}},
                "pivotTable": {"*": {"grid": [{"gridVertical": False, "gridHorizontal": False, "outlineColor": sol(PANEL)}],
                                     "columnHeaders": [{"fontColor": sol(YEL), "backColor": sol(PANEL2), "fontFamily": FONT + " Semibold", "outline": "None"}],
                                     "rowHeaders": [{"fontColor": sol(INK), "backColor": sol(PANEL), "fontFamily": FONT + " Semibold", "outline": "None"}],
                                     "values": [{"fontColorPrimary": sol(INK), "backColorPrimary": sol(PANEL), "fontColorSecondary": sol(INK), "backColorSecondary": sol(PANEL), "fontFamily": FONT}],
                                     "subTotals": [{"rowSubtotals": False, "columnSubtotals": False}]}},
                "lineChart": {"*": {"lineStyles": [{"strokeWidth": 3, "showMarker": False}]}},
                "page": {"*": {"background": [{"color": sol(BG), "transparency": 0}], "outspace": [{"color": sol(BG), "transparency": 0}]}}}}

# ==================================================================== build parts
def build_parts(sm_id, page_filter="all"):
    builders = {"overview": page_overview, "demand": page_demand, "zones": page_zones, "revenue": page_revenue, "ops": page_ops}
    wanted = list(builders) if page_filter == "all" else [x.strip() for x in page_filter.split(",")]
    pages = [builders[k]() for k in wanted]
    files = {}
    files["definition.pbir"] = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                "version": "4.0", "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={sm_id}"}}}
    files["definition/version.json"] = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}
    files["definition/report.json"] = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.1.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY25SU12", "reportVersionAtImport": {"visual": "2.5.0", "report": "3.1.0", "page": "2.3.0"}, "type": "SharedResources"},
                            "customTheme": {"name": "NYCTaxiNight.json", "reportVersionAtImport": {"visual": "2.5.0", "report": "3.1.0", "page": "2.3.0"}, "type": "RegisteredResources"}},
        "objects": {"outspacePane": [{"properties": {"expanded": lit(False), "visible": lit(False)}}]},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources", "items": [{"name": "CY25SU12", "path": "BaseThemes/CY25SU12.json", "type": "BaseTheme"}]},
                             {"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "NYCTaxiNight.json", "path": "NYCTaxiNight.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultFilterActionIsDataFilter": True, "defaultDrillFilterOtherVisuals": True, "useEnhancedTooltips": True, "hideVisualContainerHeader": False},
        "slowDataSourceSettings": {"isCrossHighlightingDisabled": False, "isSlicerSelectionsButtonEnabled": False, "isFilterSelectionsButtonEnabled": False, "isFieldWellButtonEnabled": False, "isApplyAllButtonEnabled": False}}
    files["StaticResources/RegisteredResources/NYCTaxiNight.json"] = theme()
    files["definition/pages/pages.json"] = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
                                            "pageOrder": [p.name for p in pages], "activePageName": pages[0].name}
    for p in pages:
        files[f"definition/pages/{p.name}/page.json"] = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
                                                         "name": p.name, "displayName": p.display, "displayOption": "FitToPage", "height": H, "width": W,
                                                         "objects": {"background": [{"properties": {"color": color(BG), "transparency": lit(0)}}],
                                                                     "outspace": [{"properties": {"color": color(BG), "transparency": lit(0)}}]}}
        for v in p.visuals:
            pos = v["position"]
            assert pos["x"] + pos["width"] <= W and pos["y"] + pos["height"] <= H, (p.name, v["name"], pos)
            files[f"definition/pages/{p.name}/visuals/{v['name']}/visual.json"] = v
    parts = [{"path": path, "payload": base64.b64encode(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode(), "payloadType": "InlineBase64"}
             for path, obj in files.items()]
    print(f"{len(pages)} pages, {sum(len(p.visuals) for p in pages)} visuals, {len(parts)} parts")
    return parts

# CELL ********************

client = fabric.FabricRestClient()
ws = fabric.get_workspace_id()

def post_lro(path, body):
    """POST and, when Fabric answers 202 (long running operation), poll until it completes; return the final response."""
    r = client.post(path, json=body)
    if r.status_code != 202:
        r.raise_for_status()
        return r
    op = r.headers["x-ms-operation-id"]
    while True:
        time.sleep(int(r.headers.get("Retry-After", 5)))
        st = client.get(f"/v1/operations/{op}").json()
        if st["status"] in ("Succeeded", "Failed"):
            break
    if st["status"] != "Succeeded":
        raise RuntimeError(f"operation {op} failed: {json.dumps(st.get('error'))}")
    try:
        return client.get(f"/v1/operations/{op}/result")
    except Exception:
        return r

items = client.get(f"/v1/workspaces/{ws}/items").json()["value"]
models = [i for i in items if i["type"] == "SemanticModel" and i["displayName"] == semantic_model_name]
if not models:
    raise ValueError(f"Semantic model '{semantic_model_name}' not found in workspace {ws}")
sm_id = models[0]["id"]
print(f"binding report to semantic model {semantic_model_name} ({sm_id})")

parts = build_parts(sm_id, pages)
existing = [i for i in items if i["type"] == "Report" and i["displayName"] == report_name]
t0 = time.time()
if existing:
    rid = existing[0]["id"]
    post_lro(f"/v1/workspaces/{ws}/reports/{rid}/updateDefinition", {"definition": {"parts": parts}})
    print(f"updated report {report_name} ({rid}) in {time.time() - t0:.0f}s")
else:
    body = {"displayName": report_name, "description": "NYC Yellow Taxi 2025 analytics, generated as code and bound to the Direct Lake model",
            "definition": {"parts": parts}}
    r = post_lro(f"/v1/workspaces/{ws}/reports", body)
    try:
        rid = r.json()["id"]
    except Exception:
        rid = ""
    print(f"created report {report_name} ({rid}) in {time.time() - t0:.0f}s")
print(json.dumps({"report_id": rid, "semantic_model_id": sm_id, "pages": pages}))
