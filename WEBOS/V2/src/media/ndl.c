/* media/ndl.c - hardware video/audio output through LG's NDL DirectMedia.
 *
 * NDL is the TV's media pipeline: NDL_DirectMediaLoad() opens a hardware video
 * plane and an audio path, NDL_DirectVideoPlay()/NDL_DirectAudioPlay() feed the
 * still-encoded H.264/H.265 NAL units and the PCM samples. The library and its
 * headers DO ship in the SDK sysroot (usr/include/libndl-media, libNDL_directmedia);
 * the sim and host builds compile the stub below (no NDL).
 *
 * Video: the H.264/H.265 bitstream from the session's video_sample_cb is passed
 * straight through; NDL decodes it.
 * Audio: the session decodes Opus to S16LE PCM (chiaki_opus_decoder) and this
 * plays it as stereo 48 kHz PCM (Remote Play audio), so no OpusHead/NDL-Opus
 * quirks to handle.
 *
 * The video plane is composited by the platform, not into the LVGL surface (see
 * docs/STATUS.md: composition is unverified on this TV).
 */
#include "ndl.h"

#ifdef DRPS5_HAVE_NDL

#define NDL_DIRECTMEDIA_API_VERSION 2
#include <NDL_directmedia_v2.h>

#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "../log.h"

#define NDL_AUDIO_RATE 48000 /* Remote Play audio is 48 kHz stereo Opus */

static struct {
    bool initialized, loaded;
    uint64_t loaded_ms;
    bool video_error_logged, audio_error_logged;
    bool video_hevc;
    unsigned probe_video_samples;
    bool hevc_1080, hevc_prepended;
    uint8_t *hevc_header;
    size_t hevc_header_size;
} g;

static bool g_hdr, g_hdr_done; /* HDR profile: whether to apply HDR info, and whether done */
static int g_hdr_frames;       /* frames fed while waiting for the HDR10 SEI */
static const int hdr_default[12] = { 13250, 34500, 7500, 3000, 34000, 16000, 15635, 16450, 10000000, 50, 1000, 400 };
static void hdr_apply(const int v[12]);

/* A bit mask of Annex B NAL types; unrecognized or truncated units are ignored. */
static uint64_t hevc_types(const uint8_t *data, size_t len) {
    uint64_t types = 0;
    for (size_t i = 0; i + 3 < len; i++) {
        size_t header = 0;
        if (i + 4 < len && !data[i] && !data[i + 1] && !data[i + 2] && data[i + 3] == 1)
            header = i + 4;
        else if (!data[i] && !data[i + 1] && data[i + 2] == 1)
            header = i + 3;
        if (header) {
            types |= UINT64_C(1) << ((data[header] >> 1) & 63);
            i = header;
        }
    }
    return types;
}

/* Report only NAL types and sizes, never encoded picture data. */
static void probe_video_nals(const uint8_t *data, size_t len, unsigned sample) {
    char summary[256] = "";
    size_t used = 0, start = len, prefix = 0;
    unsigned count = 0;
    for (size_t i = 0; i + 3 <= len;) {
        size_t p = 0;
        if (i + 4 <= len && data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 0 && data[i + 3] == 1)
            p = 4;
        else if (data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 1)
            p = 3;
        if (!p) { i++; continue; }
        if (start < len && count < 12 && used < sizeof(summary)) {
            int n = snprintf(summary + used, sizeof(summary) - used, "%s%u:%zu", count ? "," : "",
                             (unsigned)((data[start + prefix] >> 1) & 0x3f), i - start - prefix);
            if (n > 0) used += (size_t)n < sizeof(summary) - used ? (size_t)n : sizeof(summary) - used;
            count++;
        }
        start = i; prefix = p; i += p;
    }
    if (start < len && start + prefix < len && count < 12 && used < sizeof(summary)) {
        snprintf(summary + used, sizeof(summary) - used, "%s%u:%zu", count ? "," : "",
                 (unsigned)((data[start + prefix] >> 1) & 0x3f), len - start - prefix);
        count++;
    }
    log_probe("hevc: sample=%u bytes=%zu nal_type:bytes=%s%s", sample, len,
              count ? summary : "none (Annex B not detected)", count >= 12 ? " [limited]" : "");
}

/* NDL wants a pts; the media-pipeline convention (ss4s) is elapsed ms since load */
static uint64_t now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

static void load_cb(int type, long long num, const char *str) {
    log_msg("ndl: callback type=0x%02x num=%lld %s", type, num, str ? str : "");
}

bool ndl_available(void) { return true; }

bool ndl_open(const stream_settings_t *stream) {
    if (g.loaded) return true;
    if (!stream) return false;
    if (!g.initialized) {
        const char *appid = getenv("APPID");
        if (!appid || !*appid) appid = "com.drps5.remoteplay";
        int r = NDL_DirectMediaInit(appid, NULL);
        if (r != 0) {
            log_event(LOG_ERR, "NDL", "DirectMediaInit failed: %s", NDL_DirectMediaGetError());
            return false;
        }
        g.initialized = true;
        log_event(LOG_OK, "NDL", "DirectMediaInit ok (%s)", appid);
    }

    NDL_DIRECTMEDIA_DATA_INFO_T info;
    memset(&info, 0, sizeof(info));
    info.video.width = (stream->width > 1920) ? 1920 : (int)stream->width;
    info.video.height = (stream->height > 1080) ? 1080 : (int)stream->height;
    bool force_h264 = (stream->height >= 1080) || (stream->codec == CODEC_H264);
    info.video.type = force_h264 ? NDL_VIDEO_TYPE_H264 : NDL_VIDEO_TYPE_H265;
    info.audio.type = NDL_AUDIO_TYPE_PCM;
    info.audio.pcm.type = NDL_AUDIO_TYPE_PCM;
    info.audio.pcm.format = NDL_DIRECTMEDIA_AUDIO_PCM_FORMAT_S16LE;
    info.audio.pcm.channelMode = NDL_DIRECTMEDIA_AUDIO_PCM_MODE_STEREO;
    info.audio.pcm.sampleRate = NDL_DIRECTMEDIA_AUDIO_PCM_SAMPLE_RATE_OF(NDL_AUDIO_RATE);

    int r = NDL_DirectMediaLoad(&info, load_cb);
    if (r != 0) {
        log_event(LOG_ERR, "NDL", "DirectMediaLoad failed: %s", NDL_DirectMediaGetError());
        return false;
    }
    int area_rc = NDL_DirectVideoSetArea(0, 0, 1920, 1080);
    int drop_rc = NDL_DirectVideoSetFrameDropThreshold(0);
    log_probe("ndl: SetArea(1920x1080)=%d SetFrameDropThreshold(0)=%d", area_rc, drop_rc);
    g_hdr = !force_h264 && (stream->hdr || stream->codec == CODEC_H265_HDR);
    g.video_hevc = !force_h264;
    g.hevc_1080 = g.video_hevc;
    g.hevc_prepended = false;
    free(g.hevc_header);
    g.hevc_header = NULL;
    g.hevc_header_size = 0;
    g.probe_video_samples = 0;
    g_hdr_done = false;
    g_hdr_frames = 0;
    if (g_hdr) {
        /* Apply default HDR10 profile immediately so hardware pipeline is HDR ready before first frame */
        hdr_apply(hdr_default);
    }
    g.loaded = true;
    g.loaded_ms = now_ms();
    log_event(LOG_OK, "NDL", "%dx%d %s%s + PCM %d Hz stereo", stream->width, stream->height,
              force_h264 ? "H.264" : "H.265", g_hdr ? " HDR" : "", NDL_AUDIO_RATE);
    return true;
}

void ndl_close(void) {
    if (g.loaded) {
        NDL_DirectMediaUnload();
        g.loaded = false;
        g_hdr_done = false;
        g_hdr_frames = 0;
        log_event(LOG_INFO, "NDL", "DirectMediaUnload ok");
    }
    free(g.hevc_header);
    g.hevc_header = NULL;
    g.hevc_header_size = 0;
}

void ndl_quit(void) {
    ndl_close();
    if (g.initialized) {
        NDL_DirectMediaQuit();
        g.initialized = false;
        log_event(LOG_INFO, "NDL", "DirectMediaQuit ok");
    }
}

/* ---------- HDR10 ----------
 * With an HDR (H.265 HDR) profile the console sends HDR10 (PQ, BT.2020); NDL renders it
 * dark unless it is told the mastering-display colour volume and content light level, so
 * pull those SEI messages (payload types 137/144) out of the bitstream and hand them to
 * NDL_DirectVideoSetHDRInfo. Standard HDR10 defaults are used if no SEI shows up.
 *
 * The TV's NDL takes NDL_DIRECTVIDEO_HDR_INFO_T by value as 15 words: the 12 mastering /
 * light-level values, then the H.265 VUI codes (transfer, primaries, matrix). The SDK
 * header still declares the old 12-int form, which leaves those 3 words to whatever is on
 * the stack, and the TV then shows the PQ/BT.2020 picture as BT.709: washed out
 * (moonlight-tv #412, fixed in ss4s by these fields; layout from webosbrew/webos-userland).
 * The UI is not touched for HDR: the TV converts its SDR graphics plane into the HDR
 * output itself (the MStar GOP SDR2HDR path in libkadaptor), so PQ-encoding it here would
 * convert it twice. */

typedef struct {
    unsigned int mastering[12]; /* G, B, R x/y, white x/y, max/min luminance, MaxCLL, MaxFALL */
    unsigned int transfer, primaries, matrix;
} ndl_hdr_info_t;
typedef int (*ndl_set_hdr_fn)(ndl_hdr_info_t info);

/* HDR10 as Remote Play sends it: SMPTE ST 2084 (16), BT.2020 primaries (9), BT.2020 NCL (9) */
enum { VUI_TRANSFER_PQ = 16, VUI_PRIMARIES_BT2020 = 9, VUI_MATRIX_BT2020_NCL = 9 };

static size_t rbsp_unescape(const uint8_t *in, size_t n, uint8_t *out, size_t cap) {
    size_t o = 0;
    for (size_t i = 0; i < n && o < cap; i++) {
        if (i + 2 < n && in[i] == 0 && in[i + 1] == 0 && in[i + 2] == 3) { /* emulation prevention */
            out[o++] = 0;
            if (o < cap) out[o++] = 0;
            i += 2;
        } else {
            out[o++] = in[i];
        }
    }
    return o;
}

static long rd32(const uint8_t *p) { return ((long)p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]; }

/* parse one H.265 SEI NAL; out[] is in NDL_DirectVideoSetHDRInfo order (G, B, R, white, lum, cll) */
static bool sei_parse_nal(const uint8_t *nal, size_t len, int out[12]) {
    if (len < 2) return false;
    uint8_t rbsp[512];
    size_t n = rbsp_unescape(nal + 2, len - 2, rbsp, sizeof(rbsp));
    bool have_master = false;
    size_t i = 0;
    while (i + 1 < n) {
        int type = 0, size = 0;
        while (i < n && rbsp[i] == 0xFF) {
            type += 255;
            i++;
        }
        if (i >= n) break;
        type += rbsp[i++];
        while (i < n && rbsp[i] == 0xFF) {
            size += 255;
            i++;
        }
        if (i >= n) break;
        size += rbsp[i++];
        if (i + (size_t)size > n) break;
        const uint8_t *p = rbsp + i;
        if (type == 137 && size >= 24) { /* mastering_display_colour_volume */
            out[0] = (p[0] << 8) | p[1]; /* G x,y */
            out[1] = (p[2] << 8) | p[3];
            out[2] = (p[4] << 8) | p[5]; /* B x,y */
            out[3] = (p[6] << 8) | p[7];
            out[4] = (p[8] << 8) | p[9]; /* R x,y */
            out[5] = (p[10] << 8) | p[11];
            out[6] = (p[12] << 8) | p[13]; /* white point */
            out[7] = (p[14] << 8) | p[15];
            out[8] = (int)rd32(p + 16); /* max luminance */
            out[9] = (int)rd32(p + 20); /* min luminance */
            have_master = true;
        } else if (type == 144 && size >= 4) { /* content_light_level_info */
            out[10] = (p[0] << 8) | p[1];
            out[11] = (p[2] << 8) | p[3];
        }
        i += (size_t)size;
    }
    return have_master;
}

/* scan an Annex-B frame for a prefix/suffix SEI NAL carrying the HDR10 metadata */
static bool hdr_scan(const uint8_t *buf, size_t size, int out[12]) {
    size_t i = 0;
    bool found = false;
    while (i + 3 < size) {
        if (!(buf[i] == 0 && buf[i + 1] == 0)) {
            i++;
            continue;
        }
        size_t sc = buf[i + 2] == 1 ? 3 : (i + 4 <= size && buf[i + 2] == 0 && buf[i + 3] == 1 ? 4 : 0);
        if (!sc) {
            i++;
            continue;
        }
        size_t nal = i + sc, j = nal;
        while (j + 3 <= size && !(buf[j] == 0 && buf[j + 1] == 0 &&
                                  (buf[j + 2] == 1 || (j + 3 <= size && buf[j + 2] == 0 && buf[j + 3] == 1))))
            j++;
        size_t end = j + 3 <= size ? j : size;
        if (nal + 2 <= end) {
            int t = (buf[nal] >> 1) & 0x3F; /* H.265 prefix (39) / suffix (40) SEI */
            if ((t == 39 || t == 40) && sei_parse_nal(buf + nal, end - nal, out)) found = true;
        }
        i = end > i ? end : i + 1;
    }
    return found;
}

static void hdr_apply(const int v[12]) {
    ndl_hdr_info_t info = { .transfer = VUI_TRANSFER_PQ,
                            .primaries = VUI_PRIMARIES_BT2020,
                            .matrix = VUI_MATRIX_BT2020_NCL };
    for (int i = 0; i < 12; i++) info.mastering[i] = (unsigned int)v[i];
    ndl_set_hdr_fn set_hdr = (ndl_set_hdr_fn)(void (*)(void))NDL_DirectVideoSetHDRInfo;
    int r = set_hdr(info);
    log_event(r == 0 ? LOG_OK : LOG_ERR, "NDL",
              "HDR %s: prim G(%d,%d) B(%d,%d) R(%d,%d) wp(%d,%d) lum %d..%d cll %d/%d vui %u/%u/%u",
              r == 0 ? "set" : "failed", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11],
              info.transfer, info.primaries, info.matrix);
    log_msg("ndl: HDR10 output, UI kept sRGB (the TV maps its graphics plane into HDR)");
    g_hdr_done = true;
}

bool ndl_push_video(const uint8_t *nal, size_t len, int64_t pts_us) {
    (void)pts_us;
    if (!g.loaded || !nal || !len) return false;

    const uint8_t *submit = nal;
    size_t submit_len = len;
    uint8_t *combined = NULL;
    if (g.hevc_1080) {
        uint64_t types = hevc_types(nal, len);
        const uint64_t sets = (UINT64_C(1) << 32) | (UINT64_C(1) << 33) | (UINT64_C(1) << 34);
        const uint64_t pictures = (UINT64_C(1) << 32) - 1;
        const uint64_t random_access = ((UINT64_C(1) << 24) - 1) & ~((UINT64_C(1) << 16) - 1);
        if ((types & sets) == sets && !(types & pictures) && len <= 65536) {
            uint8_t *copy = malloc(len);
            if (copy) {
                memcpy(copy, nal, len);
                free(g.hevc_header);
                g.hevc_header = copy;
                g.hevc_header_size = len;
                log_msg("hevc: cached parameter sets (%zu bytes, held for IDR prepend)", len);
            }
            return true;
        } else if ((types & random_access) && !(types & sets) && g.hevc_header && len <= 4 * 1024 * 1024) {
            combined = malloc(g.hevc_header_size + len);
            if (combined) {
                memcpy(combined, g.hevc_header, g.hevc_header_size);
                memcpy(combined + g.hevc_header_size, nal, len);
                submit = combined;
                submit_len = g.hevc_header_size + len;
                if (!g.hevc_prepended) {
                    g.hevc_prepended = true;
                    log_msg("hevc: prepending %zu bytes of parameter sets to random-access sample", g.hevc_header_size);
                }
            }
        } else if ((types & random_access) && (types & sets) == sets && !g.hevc_prepended) {
            g.hevc_prepended = true;
            log_msg("hevc: random-access sample already includes parameter sets");
        }
    }

    if (g_hdr && g_hdr_frames < 60) {
        g_hdr_frames++;
        int v[12] = { 0 };
        if (hdr_scan(nal, len, v)) {
            hdr_apply(v);
            g_hdr_frames = 60;
        }
    }

    bool probe = g.video_hevc && log_probe_on() && g.probe_video_samples < 8;
    unsigned sample = probe ? ++g.probe_video_samples : 0;
    if (probe) probe_video_nals(nal, len, sample);
    long long pts = (long long)(now_ms() - g.loaded_ms);
    int r = NDL_DirectVideoPlay((void *)submit, (unsigned int)submit_len, pts);
    free(combined);
    if (probe) {
        int queued = -1;
        int queue_rc = NDL_DirectVideoGetRenderBufferLength(&queued);
        log_probe("hevc: sample=%u pts=%lld submit_rc=%d queue_rc=%d queue=%d", sample, pts, r, queue_rc, queued);
    }
    if (r != 0) {
        if (!g.video_error_logged) {
            g.video_error_logged = true;
            log_event(LOG_ERR, "NDL", "DirectVideoPlay failed: %s", NDL_DirectMediaGetError());
        }
        return false;
    }
    return true;
}

bool ndl_push_audio(const uint8_t *pcm, size_t len, int64_t pts_us) {
    (void)pts_us;
    if (!g.loaded || !pcm || !len) return false;
    int r = NDL_DirectAudioPlay((void *)pcm, (unsigned int)len, (long long)(now_ms() - g.loaded_ms));
    if (r != 0) {
        if (!g.audio_error_logged) {
            g.audio_error_logged = true;
            log_event(LOG_ERR, "NDL", "DirectAudioPlay failed: %s", NDL_DirectMediaGetError());
        }
        return false;
    }
    return true;
}

int ndl_video_buffered(void) {
    int n = -1;
    return g.loaded && NDL_DirectVideoGetRenderBufferLength(&n) == 0 ? n : -1;
}

int ndl_audio_buffered_ms(void) {
    int avail = 0, total = 0;
    if (!g.loaded || NDL_DirectAudioGetAvailableBufferSize(&avail) != 0 ||
        NDL_DirectAudioGetTotalBufferSize(&total) != 0)
        return -1;
    return total >= avail ? (total - avail) / (NDL_AUDIO_RATE * 2 * (int)sizeof(int16_t) / 1000) : -1;
}

#else /* !DRPS5_HAVE_NDL: host tests and the simulator have no NDL */

bool ndl_available(void) { return false; }
int ndl_video_buffered(void) { return -1; }
int ndl_audio_buffered_ms(void) { return -1; }

bool ndl_open(const stream_settings_t *stream) {
    (void)stream;
    return false;
}
void ndl_close(void) {}
void ndl_quit(void) {}

bool ndl_push_video(const uint8_t *nal, size_t len, int64_t pts_us) {
    (void)nal;
    (void)len;
    (void)pts_us;
    return false;
}
bool ndl_push_audio(const uint8_t *pcm, size_t len, int64_t pts_us) {
    (void)pcm;
    (void)len;
    (void)pts_us;
    return false;
}

#endif /* DRPS5_HAVE_NDL */
