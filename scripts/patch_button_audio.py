"""Narrow, repeatable patch to BlueALSA 4's configuration defaults."""
from pathlib import Path
import sys
path=Path(sys.argv[1]);text=path.read_text()
marker='/* HLauncher projection voice proxy */'
if marker not in text:
    assert '.hfp.xapl_product_name = "BlueALSA"' in text
    text=text.replace('.hfp.xapl_product_name = "BlueALSA"','.hfp.xapl_product_name = "iPhone"')
    text=text.replace('.hfp.xapl_features =\n', '.hfp.xapl_features =\n\t\t8 | '+marker+'\n')
    text=text.replace('.hfp.features_rfcomm_ag =\n', '.hfp.features_rfcomm_ag =\n\t\t(1 << 2) | /* HFP AG voice recognition */\n')
    text=text.replace('.hfp.features_sdp_ag =\n', '.hfp.features_sdp_ag =\n\t\t(1 << 2) | /* SDP AG voice recognition */\n')
    path.write_text(text)
assert marker in path.read_text()
