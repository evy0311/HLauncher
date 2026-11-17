# Vehicle compatibility

HLauncher is expected to work on factory Honda radios that have an HDMI input
for the front display and use the legacy **HondaLink Connect** phone-app protocol.
Honda called this integration **HondaLink Next Generation**. The compatibility
research points to a shared protocol across those radios. Compatibility cannot
be guaranteed. Verify compatibility with your own vehicle and head unit, since
factory equipment varies by trim, model year, and market. See the
[protocol notes](protocol.md) and [Honda's HDMI/HondaLink service article][honda-hdmi].

Acura radios with equivalent HDMI and Bluetooth app integration are expected to
be adaptable. HLauncher currently identifies itself to the radio as a HondaLink
app. Acura support will need changes to present the app identity the radio expects,
such as **AcuraLink Navigation** on the ILX Premium, followed by an in-car test.
See [Acura's original HDMI and Bluetooth connection instructions (PDF)][acuralink-navigation].

## Tested and working

| Model year | Vehicle | Market | Radio |
| --- | --- | --- | --- |
| 2014 | Honda Civic Si | US | Original HDMI-equipped HondaLink Display Audio |

## Likely supported, pending an HLauncher test

| Model years | Vehicle | Market | Factory radio or trim | Sources |
| --- | --- | --- | --- | --- |
| 2014–2015 | Honda Civic sedan and coupe | US | EX, EX-L and Si with HDMI Display Audio. Includes the 2015 SE sedan with HDMI Display Audio. | [Honda service article][honda-hdmi], [2015 Civic launch][civic-2015], [2015 audio guide][civic-2015-audio] |
| 2014–2015 | Honda Civic Hybrid | US | Hybrid and Hybrid with Leather with HDMI Display Audio. | [Honda service article][honda-hdmi], [2015 Hybrid specs][civic-hybrid] |
| 2014–2015 | Honda Civic Natural Gas | US | Factory HDMI Display Audio. | [2014 reference guide][civic-cng-2014], [2015 brochure][civic-cng-2015] |
| 2015–2016 | Honda CR-V | US | EX, EX-L and Touring. | [Honda service article][honda-hdmi] |
| 2016 | Honda CR-Z | US | LX, EX and EX-L Navi with HDMI Display Audio. | [Specs][crz-specs], [audio guide][crz-audio] |
| 2015–2017 | Honda Fit | US | EX and EX-L, including EX-L with navigation. | [Honda service article][honda-hdmi], [2017 specs][fit-2017] |
| 2016–2018 | Honda HR-V | US | EX and EX-L Navi. | [Honda service article][honda-hdmi], [2018 specs][hrv-2018] |

## Acura candidate requiring software changes

| Model years | Vehicle | Market | Factory radio or trim | Sources |
| --- | --- | --- | --- | --- |
| 2016–2018 | Acura ILX | US | Premium Package with the HDMI port for tethered AcuraLink Navigation. | [2016 press kit][ilx-2016], [2017 audio guide][ilx-2017], [2018 audio guide][ilx-2018] |

[Report your hardware setup](https://github.com/evy0311/HLauncher/issues/new?template=compatibility.yml)
with your market, model year, trim, radio, and what worked. Working, partial,
and unsuccessful setups are welcome.

[honda-hdmi]: https://static.nhtsa.gov/odi/tsbs/2018/MC-10149645-9999.pdf
[civic-2015]: https://hondanews.com/en-US/honda-automobiles/releases/release-4040e16443614f429f28abb6349c44d9-style-substance-and-performance-come-together-as-honda-civic-returns-for-2015-with-new-high-value-special-edition-sedan
[civic-2015-audio]: https://owners.honda.com/utility/download?path=%2Fstatic%2Fpdfs%2F2015%2FCivic+Sedan%2F2015_Civic_Audio_Operation.pdf
[civic-hybrid]: https://hondanews.com/en-US/honda-automobiles/releases/release-effec58ddd6f42d094e10221f4b2e60e-2015-honda-civic-hybrid-specifications-features
[civic-cng-2014]: https://techinfo.honda.com/rjanisis/pubs/QS/R014B2QS.pdf
[civic-cng-2015]: https://automobiles.honda.com/images/2015/civic-natural-gas/downloads/2015-civic-natural-gas-brochure.pdf
[crz-specs]: https://hondanews.com/en-US/releases/release-21b90b8424924c90a2627ed7d08aa499-2016-cr-z-specifications-features
[crz-audio]: https://owners.honda.com/utility/download?path=%2Fstatic%2Fpdfs%2F2016%2FCR-Z%2F2016_CR-Z_Audio_and_Connectivity.pdf
[fit-2017]: https://hondanews.com/en-US/honda-automobiles/releases/release-fea96a3372434702bc0a28a591f8f3aa-2017-honda-fit-specifications-and-features
[hrv-2018]: https://hondanews.com/en-US/honda-automobiles/releases/release-f3a08c7338dc4ae9a1093787d5e3f3ad-2018-hr-v-specifications-features
[acuralink-navigation]: https://www.acura.ca/Content/acura.ca/0e505ec6-8709-4881-a18d-0c89407ed5f8/GenericContent_FFH/AcuraLink_Job%20Aid_Final_EN.pdf#page=2
[ilx-2016]: https://acuranews.com/en-US/releases/release-81698aa263284cb7a904125201f2b161-2016-acura-ilx-overview
[ilx-2017]: https://owners.acura.com/utility/download?path=%2Fstatic%2Fpdfs%2F2017%2FILX%2F2017_ILX_All_Audio_Connections.pdf
[ilx-2018]: https://owners.acura.com/utility/download?path=%2Fstatic%2Fpdfs%2F2018%2FILX%2F2018_ILX_Audio_Connections.pdf
