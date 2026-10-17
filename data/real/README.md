# Real telemetry used by ClusterDoctor

`kalos_events.json` is derived from **AcmeTrace**, the utilization traces of the Kalos GPU cluster released by the
Shanghai AI Laboratory.

- **Source:** https://huggingface.co/datasets/Qinghao/AcmeTrace
- **License:** CC-BY-4.0, https://creativecommons.org/licenses/by/4.0/
- **Paper:** Qinghao Hu et al. *Characterization of Large Language Model Development in the Datacenter*. NSDI '24.
  arXiv:2403.07648, https://arxiv.org/abs/2403.07648
- **Changes made here:** a subset only. Two 3-hour windows around two Xid 94 events (2023-08-28 and 2023-08-18, UTC+8),
  columns limited to the 8 GPUs of one node each, GPU utilization, temperature and power only, converted from CSV to JSON.
  The Xid series of the target GPU is reconstructed from a bisection search of `XID_ERRORS.csv`: 0 before the first row that
  shows code 94, 94 after. Node and GPU ids are the dataset's own. Values are unchanged; missing values stay missing.
- **Not redistributed:** the raw CSV files (`data/raw/`, git-ignored). Rebuild this file with `scripts/build_real_slices.py`
  after fetching the windows with `scripts/kalos_fetch_events.py`.

The Xid code meanings used by the `xid_lookup` tool (31, 43, 45, 94) come from NVIDIA's Xid catalog:
https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html
