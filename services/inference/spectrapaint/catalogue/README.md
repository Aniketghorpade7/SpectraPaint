# catalogue — Shades the Dealer sells

Loaded from a swappable, versioned data file into SQLite for fast search and grouping.
The file remains the source of truth. One Catalogue at a time.

Per Shade: Shade Code, name, Shade Family, Lab value. Finish is metadata only in V1.

The file format is specified in [`data/catalogue/README.md`](../../../../data/catalogue/README.md).

---

## Where the file comes from

`location.py`, and nowhere else — "swap the file and the Catalogue changes, with no code change"
needs one place it can be true.

| | |
|---|---|
| `SPECTRAPAINT_CATALOGUE_FILE` | An explicit path, and the way the packaged app works: Electron knows where the file was installed and passes it in the service's environment. Also the override for a Dealer running a different manufacturer's file. |
| `data/catalogue/` | The development fallback, used when the variable is unset. Must hold **exactly one** JSON file. |

Exactly one, deliberately. Choosing the newest of several would let a stale file left beside a new
one decide which Shades the Dealer sells, and the two would differ in ways nobody notices until a
saved Consultation disagrees with the screen.

There is no bundled default Catalogue and no fallback to an empty one. A service quietly serving the
wrong Shades, or none, looks exactly like a working one until a Customer is at the counter — so a
missing or ambiguous file **fails at launch**, with a plain-language message for the Dealer and the
path in the log for whoever set the machine up (conventions.md §5).

```bash
# Load a different Catalogue — no code change, no rebuild
SPECTRAPAINT_CATALOGUE_FILE=/path/to/arun-2027-01.json python -m spectrapaint
```

```powershell
# Windows
$env:SPECTRAPAINT_CATALOGUE_FILE = "C:\path\to\arun-2027-01.json"; python -m spectrapaint
```
