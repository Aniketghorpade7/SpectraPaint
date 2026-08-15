# storage — what is kept

    Bundle (renameable) -> Consultation -> Photo -> Wall Plane -> Render

SQLite in the OS per-user application data directory. Renders stored as full-resolution
lossless PNG; reopening shows the stored image, never a regenerated one.

Every Render records the execution profile, the rendering mode, the Shade Code, its resolved
colour values, and the Catalogue version and identity.

Nothing is deleted automatically.
