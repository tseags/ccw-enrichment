"""
CCW County Source Registry
All 45 California counties with published CCW vendor lists.
source_type options: "pdf" | "webpage" | "google_drive_pdf" | "portal" | "webpage_embeds_pdf"
"""

COUNTIES = {
    # --- DIRECT PDF (30 counties) ---
    # These URLs serve PDFs directly. pdfplumber handles all of them.
    "alpine": {
        "name": "Alpine County",
        "source_url": "https://permitium-downloads.s3.us-east-1.amazonaws.com/Alpine+PD/CCW_Instructors.pdf",
        "source_type": "pdf",
        "vendor_count": 5,
        "notes": "S3-hosted Permitium PDF",
    },
    "amador": {
        "name": "Amador County",
        "source_url": "https://cdn.prod.website-files.com/654e71019f991190fc202044/694054907e63abf37ed1430b_10-23-25-AmadorSO_Approved-CCW-Vendor-list-Rev-101624-(1)-a844f5.pdf",
        "source_type": "pdf",
        "vendor_count": 34,
        "notes": "Webflow CDN hosted PDF",
    },
    "butte": {
        "name": "Butte County",
        "source_url": "https://www.buttecounty.net/DocumentCenter/View/15396/CCW-Providers-04-14-25",
        "source_type": "pdf",
        "vendor_count": 16,
        "notes": "CivicPlus DocumentCenter — serves PDF directly",
    },
    "fresno": {
        "name": "Fresno County",
        "source_url": "https://www.fresnosheriff.org/images/pdfs/01052026%20CCW%20Instructor%20List.pdf",
        "source_type": "pdf",
        "vendor_count": 84,
        "notes": "Direct PDF link",
    },
    "glenn": {
        "name": "Glenn County",
        "source_url": "https://www.countyofglenn.net/sites/default/files/resources/2026_01_Instructors%2001.2026.pdf",
        "source_type": "pdf",
        "vendor_count": 21,
        "notes": "Drupal-hosted PDF",
    },
    "imperial": {
        "name": "Imperial County",
        "source_url": "https://permitium-downloads.s3.amazonaws.com/Imperial+Sheriff/Imperial_Instructors.pdf",
        "source_type": "pdf",
        "vendor_count": 5,
        "notes": "S3-hosted Permitium PDF",
    },
    "inyo": {
        "name": "Inyo County",
        "source_url": "https://www.inyocounty.us/sites/default/files/2025-04/2025%20CCW%20TRAINING%20AND%20TRAINERS_0.pdf",
        "source_type": "pdf",
        "vendor_count": 4,
        "notes": "Drupal-hosted PDF",
    },
    "kings": {
        "name": "Kings County",
        "source_url": "https://www.countyofkingsca.gov/home/showpublisheddocument/37203/638792056595470000",
        "source_type": "pdf",
        "vendor_count": 46,
        "notes": "CivicPlus/Granicus showpublisheddocument — serves PDF",
    },
    "lassen": {
        "name": "Lassen County",
        "source_url": "https://www.lassencounty.org/sites/default/files/Approved%20CCW%20Instructor%20List%208_15_25.pdf",
        "source_type": "pdf",
        "vendor_count": 19,
        "notes": "Direct PDF link",
    },
    "los-angeles": {
        "name": "Los Angeles County",
        "source_url": "https://permitium-downloads.s3.amazonaws.com/LASD/LASD_AUTHORIZED_TRAINING_PROVIDERS.pdf",
        "source_type": "pdf",
        "vendor_count": 45,
        "notes": "S3-hosted Permitium PDF",
    },
    "madera": {
        "name": "Madera County",
        "source_url": "https://www.maderacounty.com/home/showpublisheddocument/47320/639082197202600000",
        "source_type": "pdf",
        "vendor_count": 64,
        "notes": "CivicPlus/Granicus — confirmed tabular PDF. Columns: Business Name | Phone | Email | Instructor",
    },
    "modoc": {
        "name": "Modoc County",
        "source_url": "https://www.modocsheriff.us/sites/g/files/vyhlif921/f/pages/modoc_county_sheriffs_office_approved_instructors.pdf",
        "source_type": "pdf",
        "vendor_count": 22,
        "notes": "Direct PDF link",
    },
    "nevada": {
        "name": "Nevada County",
        "source_url": "https://www.nevadacountyca.gov/DocumentCenter/View/52728/CCW-Approved-Training-Vendors-List",
        "source_type": "pdf",
        "vendor_count": 24,
        "notes": "CivicPlus DocumentCenter",
    },
    "orange": {
        "name": "Orange County",
        "source_url": "https://www.ocsheriff.gov/sites/ocsd/files/2026-03/CCW%20Training%20Providers%20REV%203-6-2026.pdf",
        "source_type": "pdf",
        "vendor_count": 43,
        "notes": "Direct PDF link",
    },
    "plumas": {
        "name": "Plumas County",
        "source_url": "https://www.plumascounty.us/DocumentCenter/View/52428/APPROVED-CCW-INSTRUCTORS-LIST1-26-2026?bidId=",
        "source_type": "pdf",
        "vendor_count": 19,
        "notes": "CivicPlus DocumentCenter",
    },
    "riverside": {
        "name": "Riverside County",
        "source_url": "https://permitium-downloads.s3.amazonaws.com/Riverside/RSO_VendorList.pdf",
        "source_type": "pdf",
        "vendor_count": 68,
        "notes": "S3-hosted Permitium PDF",
    },
    "san-diego": {
        "name": "San Diego County",
        "source_url": "https://www.sdsheriff.gov/home/showpublisheddocument/10012/639107112907930000",
        "source_type": "pdf",
        "vendor_count": 67,
        "notes": "CivicPlus — confirmed. ALL CAPS vendor names = block delimiter. Has course type icons in footer (ignore).",
    },
    "san-joaquin": {
        "name": "San Joaquin County",
        "source_url": "https://sjsheriff.org/wp-content/uploads/2025/04/CCW-Vendor-List-2026.pdf",
        "source_type": "pdf",
        "vendor_count": 25,
        "notes": "WordPress-hosted PDF",
    },
    "san-luis-obispo": {
        "name": "San Luis Obispo County",
        "source_url": "https://www.slosheriff.org/wp-content/uploads/2025/08/Approved-CCW-Qualification-Vendors.pdf",
        "source_type": "pdf",
        "vendor_count": 5,
        "notes": "WordPress-hosted PDF",
    },
    "santa-clara": {
        "name": "Santa Clara County",
        "source_url": "https://files.santaclaracounty.gov/exjcpb1376/2025-09/vendor-list-pdf-9.18.25.pdf?VersionId=N8KdWrEpm6JMZ3VRqXL9._xwMhhJLBBA",
        "source_type": "pdf",
        "vendor_count": 20,
        "notes": "Direct PDF with versioned S3-style URL",
    },
    "santa-cruz": {
        "name": "Santa Cruz County",
        "source_url": "https://shf.santacruzcountyca.gov/Portals/1/County/sheriff/formsdocs/Approved_CCW_Instructor_list.pdf",
        "source_type": "pdf",
        "vendor_count": 14,
        "notes": "DNN Portals-hosted PDF",
    },
    "shasta": {
        "name": "Shasta County",
        "source_url": "https://www.shastacounty.gov/media/75061",
        "source_type": "pdf",
        "vendor_count": 25,
        "notes": "Drupal /media/ URL — should redirect to PDF",
    },
    "sierra": {
        "name": "Sierra County",
        "source_url": "https://www.sierracounty.ca.gov/DocumentCenter/View/11816/Approved-CCW-Instructors",
        "source_type": "pdf",
        "vendor_count": 8,
        "notes": "CivicPlus DocumentCenter",
    },
    "siskiyou": {
        "name": "Siskiyou County",
        "source_url": "https://www.siskiyoucounty.gov/sites/default/files/fileattachments/sheriff039s_office/page/6491/2026_online_inst_list.pdf",
        "source_type": "pdf",
        "vendor_count": 15,
        "notes": "Drupal-hosted PDF",
    },
    "solano": {
        "name": "Solano County",
        "source_url": "https://content.solanocounty.gov/sites/default/files/2025-05/Solano%20County%20CCW%20Approved%20Trainers.pdf",
        "source_type": "pdf",
        "vendor_count": 12,
        "notes": "Actual PDF URL extracted from wrapped archival-document URL",
    },
    "stanislaus": {
        "name": "Stanislaus County",
        "source_url": "https://www.scsdonline.com/home/showpublisheddocument/3247/639078284998330000",
        "source_type": "pdf",
        "vendor_count": 14,
        "notes": "CivicPlus/Granicus showpublisheddocument",
    },
    "tehama": {
        "name": "Tehama County",
        "source_url": "https://tehamaso.org/wp-content/uploads/2025/06/CERTIFIED-INSTRUCTOR-LIST-last-updated-6-10-25.pdf",
        "source_type": "pdf",
        "vendor_count": 32,
        "notes": "WordPress-hosted PDF",
    },
    "trinity": {
        "name": "Trinity County",
        "source_url": "https://www.trinitycounty.org/DocumentCenter/View/3358/FEE-AND-INSTRUCTORS-DEC-2025?bidId=",
        "source_type": "pdf",
        "vendor_count": 19,
        "notes": "CivicPlus DocumentCenter. Also contains fee schedule — skip fee rows.",
    },
    "yuba": {
        "name": "Yuba County",
        "source_url": "https://cms7files.revize.com/yubaca/Yuba%20County/Sheriff/CCW/CCW%20Instructors%20list%207-1-25.pdf",
        "source_type": "pdf",
        "vendor_count": 19,
        "notes": "Revize CMS hosted PDF",
    },

    # --- HTML WEBPAGES (11 counties) ---
    # Fetch HTML, parse with BeautifulSoup + Claude API
    "calaveras": {
        "name": "Calaveras County",
        "source_url": "https://sheriff.calaverasgov.us/Records-Civil/CCW",
        "source_type": "webpage",
        "vendor_count": 36,
        "notes": "DNN CMS. Clean vendor cards: h3=name, then instructor/city/phone/email. Confirmed working.",
    },
    "humboldt": {
        "name": "Humboldt County",
        "source_url": "https://humboldtgov.org/342/Concealed-Weapons-Permit",
        "source_type": "webpage",
        "vendor_count": 9,
        "notes": "CivicPlus HTML page",
    },
    "marin": {
        "name": "Marin County",
        "source_url": "https://marinsheriff.gov/services/ccw",
        "source_type": "webpage",
        "vendor_count": 12,
        "notes": "",
    },
    "mariposa": {
        "name": "Mariposa County",
        "source_url": "https://www.mariposacounty.gov/622/Concealed-Weapons-Permits",
        "source_type": "webpage",
        "vendor_count": 14,
        "notes": "CivicPlus HTML page",
    },
    "mendocino": {
        "name": "Mendocino County",
        "source_url": "https://mendocinosheriff.org/carry-concealed-weapon-permits/",
        "source_type": "webpage",
        "vendor_count": 6,
        "notes": "WordPress page",
    },
    "merced": {
        "name": "Merced County",
        "source_url": "https://www.countyofmerced.com/3266/CCW-Approved-Instructor-Classes",
        "source_type": "webpage",
        "vendor_count": 24,
        "notes": "CivicPlus HTML page",
    },
    "napa": {
        "name": "Napa County",
        "source_url": "https://www.napacounty.gov/2511/Concealed-Weapons-Permit",
        "source_type": "webpage",
        "vendor_count": 23,
        "notes": "CivicPlus HTML page",
    },
    "placer": {
        "name": "Placer County",
        "source_url": "https://www.placer.ca.gov/6366/Approved-CCW-Instructors",
        "source_type": "webpage",
        "vendor_count": 52,
        "notes": "CivicPlus HTML page. Largest HTML county.",
    },
    "sonoma": {
        "name": "Sonoma County",
        "source_url": "https://www.sonomasheriff.org/ccw",
        "source_type": "webpage",
        "vendor_count": 6,
        "notes": "",
    },
    "tulare": {
        "name": "Tulare County",
        "source_url": "https://tularecounty.ca.gov/sheriff/community/ccw-instructor-list",
        "source_type": "webpage",
        "vendor_count": 56,
        "notes": "Second largest HTML county.",
    },
    "tuolumne": {
        "name": "Tuolumne County",
        "source_url": "https://www.tuolumnecounty.ca.gov/342/CCW",
        "source_type": "webpage",
        "vendor_count": 22,
        "notes": "CivicPlus HTML page",
    },

    # --- WEBPAGE THAT EMBEDS A PDF (2 counties) ---
    # Load the page, find the PDF download link, then fetch + parse as PDF
    "sutter": {
        "name": "Sutter County",
        "source_url": "https://www.suttersheriff.gov/divisions/training-section/ccw-permit",
        "source_type": "webpage_embeds_pdf",
        "vendor_count": 20,
        "notes": "URL has #docaccess hash — load page, find PDF link in docaccess widget, download PDF",
    },
    "ventura": {
        "name": "Ventura County",
        "source_url": "https://sheriff.venturacounty.gov/public-resources/carry-a-concealed-weapon-ccw/",
        "source_type": "webpage_embeds_pdf",
        "vendor_count": 32,
        "notes": "URL has #docaccess hash — load page, find PDF link in docaccess widget, download PDF",
    },

    # --- GOOGLE DRIVE PDF (2 counties) ---
    # Convert sharing URL to direct download URL
    "mono": {
        "name": "Mono County",
        "source_url": "https://drive.google.com/file/d/1BXezrH8fQ2BkIWX_OaEmMYyYfKEgUUgL/view?usp=sharing",
        "source_type": "google_drive_pdf",
        "vendor_count": 17,
        "notes": "Convert to: https://drive.google.com/uc?export=download&id=1BXezrH8fQ2BkIWX_OaEmMYyYfKEgUUgL",
    },
    "san-benito": {
        "name": "San Benito County",
        "source_url": "https://drive.google.com/file/d/1my2Zs9orCFpXcmmQ5gICal0FpImdNWf9/view?usp=sharing",
        "source_type": "google_drive_pdf",
        "vendor_count": 29,
        "notes": "Convert to: https://drive.google.com/uc?export=download&id=1my2Zs9orCFpXcmmQ5gICal0FpImdNWf9",
    },

    # --- PORTAL (1 county) ---
    # Blocked by Permitium portal. Use manual text file fallback.
    "el-dorado": {
        "name": "El Dorado County",
        "source_url": "https://eldoradoca.permitium.com/ccw/start",
        "source_type": "portal",
        "vendor_count": 23,
        "notes": "Permitium portal returns 403. Save vendor list manually to data/raw/el-dorado.txt",
    },
}

# Counties with no published vendor list — skip for scraping
SKIP_COUNTIES = {
    "alameda":        "no list published — contact only",
    "colusa":         "no list published — contact only",
    "contra-costa":   "no list published — contact only",
    "del-norte":      "no list published — contact only",
    "kern":           "no list published — contact only",
    "lake":           "no list published — contact only",
    "monterey":       "broken link",
    "sacramento":     "no list published — contact only",
    "san-bernardino": "no list published — contact only",
    "san-francisco":  "no list published — contact only",
    "san-mateo":      "memo-only — vendor list from applicant approval memo (not publicly posted)",
    "santa-barbara":  "no list published — contact only",
    "yolo":           "opted out — no longer publishes vendor list",
}

# Summary stats
TOTAL_COUNTIES_WITH_DATA = len(COUNTIES)           # 45
TOTAL_VENDORS_ESTIMATE = sum(
    c.get("vendor_count", 0) for c in COUNTIES.values()
)                                                   # ~1,175
