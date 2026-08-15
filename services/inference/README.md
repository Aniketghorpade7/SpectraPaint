# inference — Python service

All image and model work, exposed over HTTP on localhost.

Binds to an OS-assigned free port and requires a per-launch secret on every request.
Localhost is not private: any local process, and any web page open in the Dealer browser,
could otherwise read stored Customer photos.
