// Tiny launcher: launchd runs this, it execs the job script. Grant Full Disk Access to THIS binary only
// (not /bin/bash). exec keeps the same process, so bash/yt-dlp/ffmpeg/mv/dotnet inherit its TCC identity.
// SCRIPT is baked in at build time by `prolonged.sh install`; all argv are passed through.
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  char **a = malloc((argc + 2) * sizeof *a);
  a[0] = "/bin/bash"; a[1] = SCRIPT;
  for (int i = 1; i < argc; i++) a[i + 1] = argv[i];
  a[argc + 1] = NULL;
  execv("/bin/bash", a);
  perror("execv"); return 127;
}
