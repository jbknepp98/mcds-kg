-- ZIP code centroids for the zip-code finder. Run as mcd_admin. Re-runnable.
CREATE TABLE IF NOT EXISTS geo.zip_code (
  zip       text PRIMARY KEY CHECK (zip ~ '^[0-9]{5}$'),
  latitude  numeric(9,6) NOT NULL CHECK (latitude BETWEEN 32 AND 37),
  longitude numeric(9,6) NOT NULL CHECK (longitude BETWEEN -95 AND -89)
);
CALL util.add_audit('geo.zip_code');
