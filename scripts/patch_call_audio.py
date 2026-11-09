#!/usr/bin/env python3
"""Keep BlueALSA's CIND call indicators consistent with its external AG handler."""
from pathlib import Path
import sys

MARKER='/* HLauncher call indicators from the external AG handler */'
HELPER='''static void hlauncher_update_call_indicators(struct ba_rfcomm *r, const char *message) {
	unsigned int index, value;
	if (!(r->sco->type.profile & BA_TRANSPORT_PROFILE_HFP_AG))
		return;
	if (sscanf(message, "\\r\\n+CIEV:%u,%u", &index, &value) != 2)
		return;
	if ((index == HFP_IND_CALL && value <= 1) ||
			(index == HFP_IND_CALLSETUP && value <= 3) ||
			(index == HFP_IND_CALLHELD && value <= 2))
		r->hfp_ind[index] = value;
}

'''
OLD='sprintf(tmp, "0,0,0,0,0,0,%d", battchg);'
NEW='''sprintf(tmp, "0,%u,%u,%u,0,0,%d", r->hfp_ind[HFP_IND_CALL],
			r->hfp_ind[HFP_IND_CALLSETUP], r->hfp_ind[HFP_IND_CALLHELD], battchg);'''
ANCHOR='static int rfcomm_handler_cind_get_cb('
WRITE="\t\t\ttmp[ret] = '\\0';\n\t\t\tif (rfcomm_write_at(pfds[1].fd, AT_TYPE_RAW, tmp, NULL) == -1)"
REPLACEMENT="\t\t\ttmp[ret] = '\\0';\n\t\t\thlauncher_update_call_indicators(r, tmp);\n\t\t\tif (rfcomm_write_at(pfds[1].fd, AT_TYPE_RAW, tmp, NULL) == -1)"


def patch_source(text):
    if MARKER in text:
        if NEW not in text or REPLACEMENT not in text:raise ValueError('Incomplete call-state patch')
        return text
    if any(text.count(value)!=1 for value in (OLD,ANCHOR,WRITE)):
        raise ValueError('Unexpected BlueALSA source; refusing an ambiguous patch')
    return text.replace(OLD,NEW).replace(ANCHOR,MARKER+'\n'+HELPER+ANCHOR).replace(WRITE,REPLACEMENT)


if __name__=='__main__':
    path=Path(sys.argv[1]);path.write_text(patch_source(path.read_text()))
