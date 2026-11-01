#!/usr/bin/env python3
"""Generates atlas/maps.json: every instance map definition for domain mcdonalds-ops."""
import json
L = "urn:atlas:ontology:mcdonalds:"
CONTAINS = "urn:atlas:ontology:atlas-common:contains"
PG, HIST = "con_c10edc", "con_faabed/McDonalds"
static = lambda v: [{"type": "StaticStrategy", "value": v}]
bound = lambda tag: [{"type": "BoundStrategy", "bindingPath": f"{HIST}/[S].{tag}"}]
def health(prop, ok, bad):
    return [{"type": "CalculatedStrategy", "functionUri": L + "ClassifyHealth", "arguments": [
        {"type": "propertyRef", "parameter": L + "param/value", "propertyUri": L + prop, "order": 0},
        {"type": "literal", "parameter": L + "param/healthyThreshold", "value": str(ok), "order": 1},
        {"type": "literal", "parameter": L + "param/dangerThreshold", "value": str(bad), "order": 2}]}]
ORG, EQ = "organization.map.json", "store-equipment.map.json"
store_cols = {  # map name -> view column, property
    "S": ("store_id", "StoreId"), "N": ("store_number", "StoreNumber"), "Dn": ("display_name", None),
    "T": ("territory_id", None), "Rn": ("restaurant_name", "RestaurantName"), "Ad": ("address", "Address"),
    "Ci": ("city", "City"), "St": ("state_code", "State"), "Z": ("zip", "Zip"), "Co": ("county_name", "County"),
    "Lat": ("latitude", "Latitude"), "Lon": ("longitude", "Longitude"), "Ph": ("phone", "Phone"),
    "Os": ("operating_status_code", "OperatingStatus"), "Op": ("is_open", "IsOpen"),
    "Lt": ("location_type_code", "LocationType"), "Rh": ("restaurant_hours", "RestaurantHours"),
    "Dh": ("drive_thru_hours", "DriveThruHours"), "H24": ("is_24_hour", "Is24Hour"),
    "Dt": ("has_drive_thru", "HasDriveThru"), "Mo": ("has_mobile_ordering", "HasMobileOrdering"),
    "De": ("has_delivery", "HasDelivery"), "Ki": ("has_kiosk", "HasKiosk"), "Pp": ("has_play_place", "HasPlayPlace")}
stores_src = {"p": {"bindingPath": f"{PG}/Stores"}}
smap = lambda names: [{"name": n, "data": f"[p.{store_cols[n][0]}]"} for n in names]
defs = [
  {"fileName": ORG, "id": "enterprise", "name": "Enterprise", "type": L + "Enterprise",
   "instanceId": "McDonalds-AR", "label": "McDonald's Arkansas",
   "properties": {L + "Name": static("McDonald's Arkansas")}},
  {"fileName": ORG, "id": "territories", "name": "Territories", "type": L + "Territory",
   "instanceId": "[T]", "label": "[Tn]", "sources": {"p": {"bindingPath": f"{PG}/Territories"}},
   "map": [{"name": "T", "data": "[p.territory_id]"}, {"name": "Tn", "data": "[p.name]"}],
   "properties": {L + "TerritoryId": static("[T]"), L + "Name": static("[Tn]")}},
  {"fileName": ORG, "id": "enterprise-contains-territory", "name": "Enterprise contains Territory", "type": CONTAINS,
   "instanceId": "contains-McDonalds-AR-[T]", "source": "McDonalds-AR", "target": "[T]",
   "sources": {"p": {"bindingPath": f"{PG}/Territories"}}, "map": [{"name": "T", "data": "[p.territory_id]"}]},
  {"fileName": ORG, "id": "stores", "name": "Stores", "type": L + "Store",
   "instanceId": "[S]", "label": "[Dn]", "sources": stores_src, "map": smap([k for k in store_cols if k != "T"]),
   "properties": {L + prop: static(f"[{n}]") for n, (_, prop) in store_cols.items() if prop}},
  {"fileName": ORG, "id": "territory-contains-store", "name": "Territory contains Store", "type": CONTAINS,
   "instanceId": "contains-[T]-[S]", "source": "[T]", "target": "[S]", "sources": stores_src, "map": smap(["S", "T"])},
]
equipment = [  # id suffix, type, label, properties
  ("Cooler", "Cooler", "Walk-in Cooler", {L+"RefrigerationState": bound("Cooler.State"), L+"Temperature": bound("Cooler.Temperature"),
                                          L+"TemperatureHealth": health("Temperature", 41, 45)}),
  ("Freezer", "Freezer", "Walk-in Freezer", {L+"RefrigerationState": bound("Freezer.State"), L+"Temperature": bound("Freezer.Temperature"),
                                             L+"TemperatureHealth": health("Temperature", 0, 10)}),
  ("HVACUnit", "HVACUnit", "Rooftop HVAC Unit", {L+"HVACState": bound("HVAC.State"), L+"SupplyAirTemperature": bound("HVAC.SupplyAirTemperature"),
                                                 L+"SupplyAirTemperatureHealth": health("SupplyAirTemperature", 72, 80)}),
  ("Generator", "Generator", "Backup Generator", {L+"GeneratorState": bound("Generator.State"), L+"LoadPercent": bound("Generator.LoadPercent"),
                                                  L+"LoadPercentHealth": health("LoadPercent", 80, 90)}),
  ("SoftServe", "SoftServeMachine", "Soft Serve Machine", {L+"SoftServeState": bound("SoftServe.State")}),
]
for suffix, typ, label, props in equipment:
    slug = suffix.lower()
    defs.append({"fileName": EQ, "id": f"store-{slug}", "name": f"Store {label}s", "type": L + typ,
                 "instanceId": f"[S]-{suffix}", "label": label, "sources": stores_src, "map": smap(["S"]),
                 "properties": {L + "StoreId": static("[S]"), **props}})
    defs.append({"fileName": EQ, "id": f"store-contains-{slug}", "name": f"Store contains {label}", "type": CONTAINS,
                 "instanceId": f"contains-[S]-{suffix}", "source": "[S]", "target": f"[S]-{suffix}",
                 "sources": stores_src, "map": smap(["S"])})
json.dump(defs, open("atlas/maps.json", "w"), indent=1)
print(len(defs), "definitions")
