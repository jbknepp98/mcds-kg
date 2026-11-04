#!/usr/bin/env python3
"""Generates atlas/maps.json: every instance map definition for domain mcdonalds-ops."""
import json, subprocess
L = "urn:atlas:ontology:mcdonalds:"
INST = "urn:atlas:instance:mcdonalds-ops:"
CONTAINS = "urn:atlas:ontology:atlas-common:contains"
PG, HIST = "con_c10edc", "con_faabed/McDonalds"
static = lambda v: [{"type": "StaticStrategy", "value": v}]
bound = lambda tag: [{"type": "BoundStrategy", "bindingPath": f"{HIST}/[S].{tag}"}]
def health(prop, ok, bad):
    return [{"type": "CalculatedStrategy", "functionUri": L + "ClassifyHealth", "arguments": [
        {"type": "propertyRef", "parameter": L + "param/value", "propertyUri": L + prop, "order": 0},
        {"type": "literal", "parameter": L + "param/healthyThreshold", "value": str(ok), "order": 1},
        {"type": "literal", "parameter": L + "param/dangerThreshold", "value": str(bad), "order": 2}]}]
ORG, EQ, SVC = "organization.map.json", "store-equipment.map.json", "service.map.json"

# Class-level health / consequence settings come from ref.equipment_class (re-run this after changing them).
_rows = subprocess.run(["docker", "exec", "bible-pg", "psql", "-U", "bible_admin", "-d", "mcdonalds_ar", "-At", "-F", "\t", "-c",
    "SELECT equipment_class_code, tag_segment, COALESCE(health_signal,''), COALESCE(normal_value::text,''), "
    "COALESCE(normal_tolerance::text,''), product_at_risk_usd, max_detour_miles, "
    "COALESCE(downtime_revenue_per_hour_usd::text,'') FROM ref.equipment_class ORDER BY 1"],
    capture_output=True, text=True, check=True).stdout.splitlines()
CLS = {r[0]: dict(seg=r[1], sig=r[2], nv=r[3], nt=r[4], usd=r[5], mi=r[6], rph=r[7]) for r in (x.split("\t") for x in _rows)}

def calc(fn, *args):
    """args: (param, ('prop', PropName) | ('lit', value))"""
    return [{"type": "CalculatedStrategy", "functionUri": L + fn, "arguments": [
        ({"type": "propertyRef", "parameter": L + "param/" + p, "propertyUri": L + v, "order": i} if k == "prop"
         else {"type": "literal", "parameter": L + "param/" + p, "value": str(v), "order": i})
        for i, (p, (k, v)) in enumerate(args)]}]

def monitored(code, state_prop):
    c = CLS[code]; tag = f"{c['seg']}.{c['sig']}"
    return {L+"EquipmentClassCode": static(code), L+"MaxDetourMiles": static(c["mi"]), L+"ProductAtRiskUsd": static(c["usd"]),
            L+"NormalValue": static(c["nv"]), L+"NormalTolerance": static(c["nt"]),
            L+"HourlyAverage": bound(tag + "Avg1h"), L+"BaselineMean": bound(tag + "BaselineMean"),
            L+"BaselineStdDev": bound(tag + "BaselineStdDev"), L+"BaselineMode": bound(tag + "BaselineMode"),
            L+"HealthIndex": calc("HealthIndexOf", ("hourlyAverage", ("prop", "HourlyAverage")), ("baselineMean", ("prop", "BaselineMean")),
                                  ("baselineStdDev", ("prop", "BaselineStdDev")), ("normalValue", ("prop", "NormalValue")),
                                  ("normalTolerance", ("prop", "NormalTolerance"))),
            L+"ServiceCondition": calc("ServiceConditionOf", ("healthIndex", ("prop", "HealthIndex")), ("state", ("prop", state_prop))),
            L+"DetourAllowanceMiles": calc("DetourAllowanceMilesOf", ("healthIndex", ("prop", "HealthIndex")),
                                           ("condition", ("prop", "ServiceCondition")), ("maxDetourMiles", ("prop", "MaxDetourMiles"))),
            L+"ExposureUsd": calc("ExposureUsdOf", ("healthIndex", ("prop", "HealthIndex")),
                                  ("condition", ("prop", "ServiceCondition")), ("productAtRiskUsd", ("prop", "ProductAtRiskUsd")))}
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
                                          L+"TemperatureHealth": health("Temperature", 41, 45), **monitored("COOLER", "RefrigerationState")}),
  ("Freezer", "Freezer", "Walk-in Freezer", {L+"RefrigerationState": bound("Freezer.State"), L+"Temperature": bound("Freezer.Temperature"),
                                             L+"TemperatureHealth": health("Temperature", 0, 10), **monitored("FREEZER", "RefrigerationState")}),
  ("HVACUnit", "HVACUnit", "Rooftop HVAC Unit", {L+"HVACState": bound("HVAC.State"), L+"SupplyAirTemperature": bound("HVAC.SupplyAirTemperature"),
                                                 L+"SupplyAirTemperatureHealth": health("SupplyAirTemperature", 72, 80), **monitored("HVAC", "HVACState")}),
  ("Generator", "Generator", "Backup Generator", {L+"GeneratorState": bound("Generator.State"), L+"LoadPercent": bound("Generator.LoadPercent"),
                                                  L+"LoadPercentHealth": health("LoadPercent", 80, 90), **monitored("GENERATOR", "GeneratorState")}),
  ("SoftServe", "SoftServeMachine", "Soft Serve Machine", {L+"SoftServeState": bound("SoftServe.State"),
      L+"EquipmentClassCode": static("SOFTSERVE"), L+"MaxDetourMiles": static(CLS["SOFTSERVE"]["mi"]),
      L+"ProductAtRiskUsd": static(CLS["SOFTSERVE"]["usd"]),
      L+"ServiceCondition": calc("SoftServeConditionOf", ("state", ("prop", "SoftServeState"))),
      L+"DetourAllowanceMiles": calc("FaultDetourAllowanceMilesOf", ("condition", ("prop", "ServiceCondition")),
                                     ("maxDetourMiles", ("prop", "MaxDetourMiles"))),
      # reliability ("based on uptime"): job-computed windows bound from the Historian, scored in Atlas
      **{L+k: bound("SoftServe." + k) for k in ("Uptime24h", "Uptime7d", "Serving7d", "Failures7d", "MtbfHours",
                                                "MttrHours", "DownMinutes", "DownHours7d")},
      L+"DowntimeRevenuePerHourUsd": static(CLS["SOFTSERVE"]["rph"]),
      L+"ReliabilityScore": calc("ReliabilityScoreOf", ("uptime7d", ("prop", "Uptime7d")), ("uptime24h", ("prop", "Uptime24h"))),
      L+"ReliabilityGrade": calc("ReliabilityGradeOf", ("reliabilityScore", ("prop", "ReliabilityScore"))),
      L+"LostSalesUsd7d": calc("LostSalesUsdOf", ("downHours", ("prop", "DownHours7d")),
                               ("revenuePerHour", ("prop", "DowntimeRevenuePerHourUsd"))),
      L+"IsServing": calc("IsServingOf", ("state", ("prop", "SoftServeState"))),
      L+"CustomerHearsBroken": calc("CustomerHearsBrokenOf", ("state", ("prop", "SoftServeState")))}),
]
for suffix, typ, label, props in equipment:
    slug = suffix.lower()
    defs.append({"fileName": EQ, "id": f"store-{slug}", "name": f"Store {label}s", "type": L + typ,
                 "instanceId": f"[S]-{suffix}", "label": label, "sources": stores_src, "map": smap(["S"]),
                 "properties": {L + "StoreId": static("[S]"), **props}})
    defs.append({"fileName": EQ, "id": f"store-contains-{slug}", "name": f"Store contains {label}", "type": CONTAINS,
                 "instanceId": f"contains-[S]-{suffix}", "source": "[S]", "target": f"[S]-{suffix}",
                 "sources": stores_src, "map": smap(["S"])})
# Health matrix on the store: references to each unit's HealthIndex, plus the worst of the four.
# The four cells are ReferenceStrategy aliases of each unit's HealthIndex. They feed StoreHealthIndex correctly,
# but this Atlas build returns them empty when read directly in Cypher (a reference to a calculated value is not
# evaluated on read; a cross-node CalculatedStrategy argument never fires at all). Read the full matrix with
# atlas/queries/health_matrix.cypher (store -> contains -> unit.HealthIndex) instead.
ref = lambda suffix: [{"type": "ReferenceStrategy", "instanceUri": f"[S]-{suffix}", "propertyUri": L + "HealthIndex"}]
store_def = next(d for d in defs if d["id"] == "stores")
store_def["properties"].update({
    L+"CoolerHealthIndex": ref("Cooler"), L+"FreezerHealthIndex": ref("Freezer"),
    L+"HVACHealthIndex": ref("HVACUnit"), L+"GeneratorHealthIndex": ref("Generator"),
    L+"StoreHealthIndex": calc("WorstHealthIndex", ("coolerIndex", ("prop", "CoolerHealthIndex")),
                               ("freezerIndex", ("prop", "FreezerHealthIndex")), ("hvacIndex", ("prop", "HVACHealthIndex")),
                               ("generatorIndex", ("prop", "GeneratorHealthIndex")))})

# Service graph: technicians, trucks, certifications, parts, repair tasks and their links.
src = lambda topic: {"p": {"bindingPath": f"{PG}/{topic}"}}
col = lambda **kw: [{"name": k, "data": f"[p.{v}]"} for k, v in kw.items()]
defs += [
  {"fileName": SVC, "id": "technicians", "name": "Technicians", "type": L + "Technician", "instanceId": "[Tid]", "label": "[Nm]",
   "sources": src("Technicians"), "map": col(Tid="technician_id", Nm="full_name", Lv="cert_level_code", Rk="level_rank",
                                              Hs="home_store_id", Hd="hire_date"),
   "properties": {L+"TechnicianId": static("[Tid]"), L+"Name": static("[Nm]"), L+"CertLevel": static("[Lv]"),
                  L+"LevelRank": static("[Rk]"), L+"HomeStoreId": static("[Hs]"), L+"HireDate": static("[Hd]")}},
  {"fileName": SVC, "id": "trucks", "name": "Service Trucks", "type": L + "ServiceTruck", "instanceId": "[Tk]", "label": "[Tk]",
   "sources": src("Trucks"), "map": col(Tk="truck_id", Mk="make", Md="model", Yr="model_year", Lp="license_plate"),
   "properties": {L+"TruckId": static("[Tk]"), L+"Name": static("[Tk] [Mk] [Md]"), L+"Make": static("[Mk]"), L+"Model": static("[Md]"),
                  L+"ModelYear": static("[Yr]"), L+"LicensePlate": static("[Lp]")}},
  {"fileName": SVC, "id": "certifications", "name": "Certifications", "type": L + "Certification", "instanceId": "CERT-[C]", "label": "[Nm]",
   "sources": src("Certifications"), "map": col(C="certification_code", Nm="name", Ib="issuing_body"),
   "properties": {L+"CertificationCode": static("[C]"), L+"Name": static("[Nm]"), L+"IssuingBody": static("[Ib]")}},
  {"fileName": SVC, "id": "parts", "name": "Parts", "type": L + "Part", "instanceId": "[Pn]", "label": "[Nm]",
   "sources": src("Parts"), "map": col(Pn="part_number", Nm="name", Ec="equipment_class_code", Uc="unit_cost_usd"),
   "properties": {L+"PartNumber": static("[Pn]"), L+"Name": static("[Nm]"), L+"EquipmentClassCode": static("[Ec]"),
                  L+"UnitCostUsd": static("[Uc]")}},
  {"fileName": SVC, "id": "repair-tasks", "name": "Repair Tasks", "type": L + "RepairTask", "instanceId": "TASK-[Rt]", "label": "[Nm]",
   "sources": src("RepairTasks"), "map": col(Rt="repair_task_code", Nm="name", Ec="equipment_class_code", Ca="condition_answered",
                                              Sy="symptom", Ml="min_level_rank", Em="est_minutes"),
   "properties": {L+"RepairTaskCode": static("[Rt]"), L+"Name": static("[Nm]"), L+"EquipmentClassCode": static("[Ec]"),
                  L+"ConditionAnswered": static("[Ca]"), L+"Symptom": static("[Sy]"), L+"MinLevelRank": static("[Ml]"),
                  L+"EstMinutes": static("[Em]")}},
  {"fileName": SVC, "id": "assigned-truck", "name": "Technician assigned Truck", "type": L + "assignedTruck",
   "instanceId": "assigned-[Tid]-[Tk]", "source": "[Tid]", "target": "[Tk]", "sources": src("TruckAssignments"),
   "map": col(Tid="technician_id", Tk="truck_id", Sd="start_date"), "properties": {L+"AssignedSince": static("[Sd]")}},
  {"fileName": SVC, "id": "holds-certification", "name": "Technician holds Certification", "type": L + "holdsCertification",
   "instanceId": "holds-[Tid]-[C]", "source": "[Tid]", "target": "CERT-[C]", "sources": src("TechnicianCertifications"),
   "map": col(Tid="technician_id", C="certification_code", Cn="certificate_number", Ex="expires_date", Cur="is_current"),
   "properties": {L+"CertificateNumber": static("[Cn]"), L+"ExpiresDate": static("[Ex]"), L+"IsCurrent": static("[Cur]")}},
  {"fileName": SVC, "id": "carries-part", "name": "Truck carries Part", "type": L + "carriesPart",
   "instanceId": "carries-[Tk]-[Pn]", "source": "[Tk]", "target": "[Pn]", "sources": src("TruckInventory"),
   "map": col(Tk="truck_id", Pn="part_number", Qh="quantity_on_hand", Pq="par_quantity", Id="inventory_date"),
   "properties": {L+"QuantityOnHand": static("[Qh]"), L+"ParQuantity": static("[Pq]"), L+"InventoryDate": static("[Id]")}},
  {"fileName": SVC, "id": "requires-certification", "name": "Task requires Certification", "type": L + "requiresCertification",
   "instanceId": "requires-[Rt]-[C]", "source": "TASK-[Rt]", "target": "CERT-[C]", "sources": src("RepairTaskCertifications"),
   "map": col(Rt="repair_task_code", C="certification_code")},
  {"fileName": SVC, "id": "requires-part", "name": "Task requires Part", "type": L + "requiresPart",
   "instanceId": "requires-[Rt]-[Pn]", "source": "TASK-[Rt]", "target": "[Pn]", "sources": src("RepairTaskParts"),
   "map": col(Rt="repair_task_code", Pn="part_number", Q="quantity"), "properties": {L+"Quantity": static("[Q]")}},
  {"fileName": SVC, "id": "based-at", "name": "Technician based at Store", "type": L + "basedAt",
   "instanceId": "based-[Tid]-[Hs]", "source": "[Tid]", "target": "[Hs]", "sources": src("Technicians"),
   "map": col(Tid="technician_id", Hs="home_store_id")},
  {"fileName": SVC, "id": "serves-territory", "name": "Technician serves Territory", "type": L + "servesTerritory",
   "instanceId": "serves-[Tid]-[Te]", "source": "[Tid]", "target": "[Te]", "sources": src("Technicians"),
   "map": col(Tid="technician_id", Te="home_territory_id")},
  {"fileName": "geography.map.json", "id": "road-distance", "name": "Store road distance to Store", "type": L + "roadDistanceTo",
   "instanceId": "road-[F]-[T]", "source": "[F]", "target": "[T]", "sources": src("StoreDistances"),
   "map": col(F="from_store_id", T="to_store_id", Rm="road_miles", Dm="drive_minutes"),
   "properties": {L+"RoadMiles": static("[Rm]"), L+"DriveMinutes": static("[Dm]")}},
]
json.dump(defs, open("atlas/maps.json", "w"), indent=1)
print(len(defs), "definitions")
