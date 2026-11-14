/**
 * The data versions a folder set up by this build carries (`migrations.current("profile")` and `("jobs")`, written
 * `<major>.<n>`). The demo and the journeys' test world build their folders by hand, so they stamp them with these
 * (as `init` and the first run stamp a real one); a Python test (`tests/core/test_migrations_unit.py`) keeps them
 * equal to the server's, so a release that adds a step fails it until this file says so.
 */
export const PROFILE_DATA_VERSION = '0.1'
export const JOBS_DATA_VERSION = '0.0'
