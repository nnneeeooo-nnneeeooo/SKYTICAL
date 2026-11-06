"""Curated supplemental Commons photo search; never treats search labels as facts."""
import concurrent.futures
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pipeline"))
import images
from common import ROOT
images.TIMEOUT=(4,10)
SPECS=[
  [
    "MV22",
    "MV-22B Osprey",
    "MV-22B"
  ],
  [
    "NH90",
    "NH90 helicopter France",
    "NH90"
  ],
  [
    "KAAN",
    "Turkish Aerospace KAAN fighter",
    "KAAN"
  ],
  [
    "TURKISH_F16",
    "Turkish Air Force F-16",
    "F-16"
  ],
  [
    "ROCAF_F16",
    "Taiwan Air Force F-16V",
    "F-16"
  ],
  [
    "CH47",
    "Taiwan Army CH-47SD",
    "CH-47"
  ],
  [
    "BLACKHAWK",
    "S-70i Black Hawk Philippine Air Force",
    "Black Hawk"
  ],
  [
    "SEAHawk",
    "Sikorsky SH-60F Seahawk",
    "SH-60F"
  ],
  [
    "US_NAVY_CARRIER",
    "US Navy aircraft carrier flight deck",
    "aircraft carrier"
  ],
  [
    "EC130",
    "Eurocopter EC130 helicopter",
    "EC130"
  ],
  [
    "AS350",
    "AS350 helicopter",
    "AS350"
  ],
  [
    "CITATION_CJ3",
    "Cessna Citation CJ3",
    "CJ3"
  ],
  [
    "CITATION_CJ4",
    "Cessna Citation CJ4",
    "CJ4"
  ],
  [
    "FAIRFORD",
    "RAF Fairford Cessna Citation",
    "Citation"
  ],
  [
    "AIRBUS_A350",
    "Airbus A350-1000",
    "A350-1000"
  ],
  [
    "AIRBUS_A320",
    "Airbus A320 aircraft exterior",
    "Airbus A320"
  ],
  [
    "ATR72",
    "ATR 72-600",
    "ATR 72"
  ],
  [
    "EMBRAER_E190",
    "Embraer E190-E2",
    "E190-E2"
  ],
  [
    "EMBRAER_E190F",
    "Embraer E190F",
    "E190"
  ],
  [
    "GULFSTREAM_G700",
    "Gulfstream G700",
    "G700"
  ],
  [
    "BUSINESS_JET",
    "Gulfstream G650",
    "G650"
  ],
  [
    "CE_EVE",
    "Eve Air Mobility eVTOL prototype",
    "Eve"
  ],
  [
    "PIVOTAL_BLACKFLY",
    "Pivotal BlackFly eVTOL",
    "BlackFly"
  ],
  [
    "JOBY_S4",
    "Joby Aviation S4 eVTOL",
    "Joby"
  ],
  [
    "SCYE",
    "Sceye HAPS airship",
    "Sceye"
  ],
  [
    "REGENT",
    "Regent Seaglider",
    "Regent"
  ],
  [
    "S4000",
    "S4000 airborne wind turbine China",
    "S4000"
  ],
  [
    "JETZERO",
    "JetZero blended wing body aircraft",
    "JetZero"
  ],
  [
    "FLYOX",
    "Singular Aircraft FlyOx 1",
    "FlyOx"
  ],
  [
    "AV_DRONE",
    "AeroVironment drone Switchblade",
    "AeroVironment"
  ],
  [
    "DRONE_HELICOPTER",
    "unmanned aerial vehicle aircraft",
    "drone"
  ],
  [
    "DRONE_TAIWAN",
    "Taiwan drone technology exhibition",
    "drone"
  ],
  [
    "DRONE_NATO",
    "NATO drone defense exercise",
    "NATO"
  ],
  [
    "GA_AIRCRAFT",
    "Piper PA-28 light aircraft",
    "Piper"
  ],
  [
    "SAAB_ASC890",
    "Saab 340 AEW&C ASC 890",
    "Saab 340"
  ],
  [
    "SAAB_GRIPEN",
    "Saab Gripen Swedish Air Force",
    "Gripen"
  ],
  [
    "SU57",
    "Sukhoi Su-57 fighter aircraft",
    "Su-57"
  ],
  [
    "F15EX",
    "F-15EX Eagle II US Air Force",
    "F-15EX"
  ],
  [
    "FA18",
    "F/A-18E Super Hornet US Navy",
    "F/A-18"
  ],
  [
    "KC390",
    "Embraer C-390 military transport",
    "C-390"
  ],
  [
    "EUROFIGHTER",
    "Eurofighter Typhoon Germany",
    "Eurofighter"
  ],
  [
    "BOMBARDIER",
    "Bombardier Global 7500",
    "Global"
  ],
  [
    "LOCKHEED",
    "Lockheed Martin headquarters",
    "Lockheed"
  ],
  [
    "IAI",
    "Israel Aerospace Industries aircraft",
    "Israel Aerospace"
  ],
  [
    "ROLLS_TRENT",
    "Rolls Royce Trent 7000 engine",
    "Trent"
  ],
  [
    "AIRPORT_ATC",
    "airport air traffic control tower",
    "control tower"
  ],
  [
    "AIRPORT_CHECKIN",
    "airport passenger check in counters",
    "check in"
  ],
  [
    "AIRPORT_SECURITY",
    "airport security checkpoint luggage screening",
    "security"
  ],
  [
    "FAA_HEADQUARTERS",
    "Federal Aviation Administration headquarters",
    "Federal Aviation"
  ],
  [
    "IATA_HEADQUARTERS",
    "IATA headquarters Montreal",
    "IATA"
  ],
  [
    "EUROCONTROL_HQ",
    "EUROCONTROL headquarters Brussels",
    "EUROCONTROL"
  ],
  [
    "NATS_RADAR",
    "NATS air traffic radar station",
    "NATS"
  ],
  [
    "NTSB_BUILDING",
    "National Transportation Safety Board headquarters",
    "Transportation Safety Board"
  ],
  [
    "US_DOT_HQ",
    "US Department of Transportation headquarters",
    "Transportation"
  ],
  [
    "BEA_FRANCE",
    "Bureau Enquêtes Analyses BEA France headquarters",
    "BEA"
  ],
  [
    "GIBRALTAR_AIRPORT",
    "Gibraltar International Airport",
    "Gibraltar"
  ],
  [
    "TAOYUAN_AIRPORT",
    "Taiwan Taoyuan International Airport terminal",
    "Taoyuan"
  ],
  [
    "CHING_CHUAN",
    "Taichung Ching Chuan Kang Airport",
    "Taichung"
  ],
  [
    "HUALIEN_AIRPORT",
    "Hualien Airport Taiwan",
    "Hualien"
  ],
  [
    "CATANIA_AIRPORT",
    "Catania Fontanarossa Airport",
    "Catania"
  ],
  [
    "NICe_AIRPORT",
    "Nice Cote Azur Airport",
    "Nice"
  ],
  [
    "SYDNEY_AIRPORT",
    "Sydney Airport Australia passenger terminal",
    "Sydney"
  ],
  [
    "CHANGI_AIRPORT",
    "Changi Airport Singapore",
    "Changi"
  ],
  [
    "N700ST",
    "Taiwan N700ST high speed rail",
    "N700ST"
  ],
  [
    "TAIWAN_HSR",
    "Taiwan High Speed Rail 700T",
    "High Speed Rail"
  ],
  [
    "GENERAL_DYNAMICS",
    "General Dynamics headquarters building",
    "General Dynamics"
  ],
  [
    "BOEING_FACTORY",
    "Boeing Everett factory",
    "Boeing Everett"
  ],
  [
    "DIEHL_FACTORY",
    "Diehl Aviation factory",
    "Diehl"
  ],
  [
    "LEONARDO_HQ",
    "Leonardo helicopters company factory",
    "Leonardo"
  ],
  [
    "HONEYWELL",
    "Honeywell Aerospace aircraft electronics",
    "Honeywell"
  ],
  [
    "AFRICAN_SAFETY",
    "air ambulance helicopter UK",
    "air ambulance"
  ],
  [
    "AVIATION_GROUNDCREW",
    "Airport ground handling ramp workers",
    "airport"
  ],
  [
    "AVIATION_FUEL",
    "aircraft refueling airport",
    "refueling"
  ],
  [
    "AVIATION_ENGINE",
    "jet aircraft engine maintenance",
    "jet engine"
  ],
  [
    "AIRLINE_HUB",
    "commercial passenger airliner airport terminal",
    "airliner"
  ],
  [
    "PRIVATE_JET",
    "Gulfstream G650 jet aircraft",
    "Gulfstream"
  ],
  [
    "IATA_CARGO",
    "airport cargo warehouse air freight",
    "cargo"
  ],
  [
    "UAC_BAIKAL",
    "LMS-901 Baikal aircraft",
    "Baikal"
  ],
  [
    "REDCROSS",
    "De Havilland Canada DHC-515 firefighting aircraft",
    "DHC"
  ],
  [
    "CANADAIR",
    "Canadair CL-415 water bomber",
    "CL-415"
  ],
  [
    "KLM",
    "KLM Royal Dutch Airlines Boeing 737",
    "KLM"
  ],
  [
    "AIRARABIA",
    "Air Arabia Airbus A320",
    "Air Arabia"
  ],
  [
    "BERMUDAIR",
    "BermudAir Embraer E175",
    "BermudAir"
  ],
  [
    "AIR_ASTANA",
    "Air Astana Airbus A321",
    "Air Astana"
  ],
  [
    "SYRIA_AIR",
    "Syrian Air Airbus A320",
    "Syrian"
  ],
  [
    "ETHIOPIAN",
    "Ethiopian Airlines Boeing 787",
    "Ethiopian"
  ],
  [
    "NIPPO_CARGO",
    "Nippon Cargo Airlines Boeing 747",
    "Nippon Cargo"
  ],
  [
    "SAFAIR",
    "FlySafair Boeing 737",
    "FlySafair"
  ],
  [
    "AEROMEXICO",
    "Aeromexico Boeing 737",
    "Aeromexico"
  ],
  [
    "FLYADEAL",
    "flyadeal Airbus A320",
    "flyadeal"
  ],
  [
    "OMANAIR",
    "Oman Air Boeing 787",
    "Oman Air"
  ],
  [
    "SALAMAIR",
    "SalamAir Airbus A320",
    "SalamAir"
  ],
  [
    "ALLIANCE",
    "Alliance Airlines Embraer E190",
    "Alliance Airlines"
  ],
  [
    "EUROATLANTIC",
    "euroAtlantic Airways Boeing 767",
    "euroAtlantic"
  ],
  [
    "FALCON2000",
    "Dassault Falcon 2000 aircraft",
    "Falcon 2000"
  ],
  [
    "FAIRCHILD_PC12",
    "Pilatus PC-12 aircraft",
    "PC-12"
  ],
  [
    "PILOT_TRAINING",
    "flight training Cessna aircraft",
    "Cessna"
  ]
]
def run(entry):
    key,query,token=entry
    try:
        photo=images.lookup_commons(query,[token],prefer_landscape=True,min_year=2007,require_all=True)
        return [key,{"query":query,"token":token,"photo":photo}]
    except Exception as exc:
        return [key,{"query":query,"token":token,"error":type(exc).__name__}]
def main():
    out={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as ex:
        for key,item in ex.map(run,SPECS):
            out[key]=item
    d={"queries":len(out),"photos":sum(bool(v.get("photo")) for v in out.values()),"items":out}
    target=ROOT/"data/photo-anchors.json"
    target.write_text(json.dumps(d,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("ANCHORS",json.dumps({"queries":d["queries"],"photos":d["photos"]}))
if __name__=="__main__":
    main()
