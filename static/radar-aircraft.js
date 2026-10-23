/* Original SKYTICAL aircraft silhouettes. Sizes are readable relative symbols,
 * not geographic footprints. Unknown ICAO types stay generic. */
(function (root) {
  "use strict";
  const paths = {
    jet: "M32 2 Q35 3 35 12 L35 25 58 40 58 44 35 37 35 51 44 58 44 61 32 57 20 61 20 58 29 51 29 37 6 44 6 40 29 25 29 12 Q29 3 32 2Z M21 31h4v10h-4z M39 31h4v10h-4z",
    wide: "M32 1 Q36 3 36 14 L36 26 61 41 61 45 36 38 36 51 46 59 46 62 32 58 18 62 18 59 28 51 28 38 3 45 3 41 28 26 28 14 Q28 3 32 1Z M19 31h5v12h-5z M40 31h5v12h-5z",
    quad: "M32 1 Q36 3 36 13 L36 26 62 41 62 45 36 38 36 51 46 59 46 62 32 58 18 62 18 59 28 51 28 38 2 45 2 41 28 26 28 13 Q28 3 32 1Z M19 31h5v12h-5z M9 37h4v11H9z M40 31h5v12h-5z M51 37h4v11h-4z",
    prop: "M32 5 Q35 6 35 15 L35 28 57 31 57 36 35 34 35 50 43 55 43 59 32 56 21 59 21 55 29 50 29 34 7 36 7 31 29 28 29 15 Q29 6 32 5Z M18 25h4v17h-4z M42 25h4v17h-4z M13 24h14v2H13z M37 24h14v2H37z",
    light: "M32 6 Q34 8 34 18 L34 28 56 29 56 34 34 34 34 49 42 52 42 56 32 54 22 56 22 52 30 49 30 34 8 34 8 29 30 28 30 18 Q30 8 32 6Z M24 12h16v2H24z",
    helicopter: "M29 17 Q32 11 35 17 L38 30 Q38 38 34 40 L34 53 43 54 43 57 32 56 21 57 21 54 30 53 30 40 Q26 38 26 30Z M5 26h54v3H5z M31 3h2v52h-2z M21 21h2v23h-2z M41 21h2v23h-2z",
    generic: "M32 7 37 27 51 41 49 45 35 38 35 51 42 56 40 59 32 56 24 59 22 56 29 51 29 38 15 45 13 41 27 27Z",
  };
  const groups = [
    ["super", "quad", 46, "A388"],
    ["quad", "quad", 42, "B741 B742 B743 B744 B748 A342 A343 A345 A346"],
    ["wide", "wide", 38, "A332 A333 A338 A339 A359 A35K B762 B763 B764 B772 B773 B77L B77W B778 B779 B788 B789 B78X MD11 DC10"],
    ["narrow", "jet", 30, "A318 A319 A320 A321 A19N A20N A21N B732 B733 B734 B735 B736 B737 B738 B739 B37M B38M B39M B3XM B752 B753 MD80 MD81 MD82 MD83 MD87 MD88 MD90 B712"],
    ["regional", "jet", 25, "E170 E175 E190 E195 E290 E295 CRJ1 CRJ2 CRJ7 CRJ9 CRJX"],
    ["prop", "prop", 26, "AT43 AT45 AT46 AT72 AT73 AT75 AT76 DH8A DH8B DH8C DH8D DHC6 SF34 SB20 F50"],
    ["light", "light", 22, "C152 C172 C182 C206 C208 C25A C25B C25C C510 C525 C550 C560 C680 C700 C750 PC12 PC24 BE20 BE30 PA28 DA40 DA42 DA62 GLF4 GLF5 GLF6 GLEX GL5T GL7T CL30 CL35 CL60 FA7X FA8X"],
    ["helicopter", "helicopter", 25, "R22 R44 R66 B06 B407 B412 EC20 EC25 EC30 EC35 EC45 EC55 H60 S76 S92 A109 A139 A169 A189"],
  ];
  function profile(typeCode) {
    const code = String(typeCode || "").trim().toUpperCase();
    const group = groups.find((entry) => entry[3].split(" ").includes(code));
    return group ? { kind: group[0], shape: group[1], size: group[2] } :
      { kind: "unknown", shape: "generic", size: 25 };
  }
  function svg(typeCode) {
    const p = profile(typeCode);
    return `<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" data-aircraft-kind="${p.kind}"><path d="${paths[p.shape]}"/></svg>`;
  }
  const api = { profile, svg };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SkyticalAircraft = api;
})(typeof window === "undefined" ? this : window);
