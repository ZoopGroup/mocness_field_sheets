# MOCNESS Canonical Field Dictionary (v2)

This starter dictionary maps canonical output keys to likely labels on forms.
Update as new variants are discovered.

## Header

- cruise
  - Cruise
- tow_moc_number
  - Tow/Moc#
  - Tow Moc
  - Tow #
- file_name
  - File Name
  - Filename
- date
  - Date
- date_unresolved
  - Derived flag when date is unreadable/ambiguous/missing
- date_unresolved_reason
  - Derived reason string
- location
  - Location
- day_night
  - D/N
  - Day/Night
- direction
  - Direction
- sea_state
  - Sea State
- wind_speed
  - Wind Speed
- local_time_from
  - Local Time from
  - Local from
- local_time_to
  - Local Time to
  - Local to
- gmt_time_from
  - GMT Time from
  - GMT from
- gmt_time_to
  - GMT Time to
  - GMT to
- net_condition
  - Net Condition
- net_mesh
  - Net Mesh
- net_size
  - Net Size
- net_type
  - Type
- sog
  - SOG
- operator
  - Operator
- start_lat
  - Start Lat
  - Start Lat Long (split)
- start_long
  - Start Long
  - Start Lat Long (split)
- end_lat
  - End Lat
  - End Lat Long (split)
- end_long
  - End Long
  - End Lat Long (split)

## Net Tow Rows

- net_number
  - Net 0, Net 1, etc. (normalized to digits only)
- time_open_local
  - Time open
- time_close_local
  - Time close
  - Time Local
  - Time Close Local
- time_close_gmt
  - Time Close GMT
- target_depth_m
  - Target Depth
- depth_max_m
  - Depth max (m)
- depth_min_m
  - Depth min (m)
- depth_m
  - Depth
  - Depth (m)
- lat
  - Lat
- lon
  - Lon
  - Long
- angle
  - Angle
- flow_counts
  - Flow Counts
- volume_filtered
  - Volume Filtered
- mwo_net
  - MWO net
- winch_speed
  - Winch Speed
- notes_table
  - Notes (table row)
- notes_notes_page
  - Notes page line matched by net number
- notes
  - Final merged note: notes_table first, then notes_notes_page

## Confidence/Uncertainty

- quality.field_confidence
  - Key path to confidence score from 0.0-1.0
  - Example: header.cruise, net_tows[0].depth_max_m
- quality.uncertain_fields
  - List of key paths that are uncertain due to handwriting, strike-through,
    or ambiguity
- quality.notes
  - Free-text audit notes from extractor