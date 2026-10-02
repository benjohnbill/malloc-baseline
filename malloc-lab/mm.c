/*
 * mm.c - 팀 비교용 baseline allocator (CS:APP 9.9.12 의 implicit free list)
 *
 * 이 파일은 책(CS:APP 3판, Figure 9.43 ~ 9.47 과 연습문제 9.8, 9.9 해답)의
 * 코드를 그대로 옮기고, 그것만으로는 mdriver 가 돌아가지 않아서 꼭 필요한
 * 부분만 더한 것이다. 어디까지가 책이고 어디부터가 추가인지를 구간 표시로
 * 구분한다. tools/audit.py 가 이 표시를 읽어서 기계로 검사한다.
 *
 * 구간 표시 (표시는 독립된 한 줄의 주석이다):
 *   @BOOK <그림/해답, 쪽>             책 코드를 공백만 다듬어 그대로 옮긴 구간
 *   @BOOK-FIX <해답, 쪽> | drop: <줄>  책 코드에서 해당 줄 하나만 지운 구간
 *   @ADDED <번호>: <이유>             책에 없어서 우리가 넣은 구간
 *   @END                             구간의 끝
 *
 * 사용법은 README.md 를 본다.
 */

/* @ADDED A1: starter mm.c 의 헤더. mem_sbrk, memcpy, size_t 가 여기서 온다. 제거 시: mem_sbrk 등 선언 없음 */
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <unistd.h>
#include <string.h>

#include "mm.h"
#include "memlib.h"
/* @END */

/* @ADDED A2: starter mm.c 의 team 정의(값도 그대로). mdriver 가 team.teamname 등을 읽는다. 제거 시: undefined reference to 'team' */
team_t team = {
    /* Team name */
    "ateam",
    /* First member's full name */
    "Harry Bovik",
    /* First member's email address */
    "bovik@cs.cmu.edu",
    /* Second member's full name (leave blank if none) */
    "",
    /* Second member's email address (leave blank if none) */
    ""};
/* @END */

/* @BOOK Fig 9.43, p.893 */
/* Basic constants and macros */
#define WSIZE       4       /* Word and header/footer size (bytes) */
#define DSIZE       8       /* Double word size (bytes) */
#define CHUNKSIZE (1<<12)   /* Extend heap by this amount (bytes) */

#define MAX(x, y) ((x) > (y)? (x) : (y))

/* Pack a size and allocated bit into a word */
#define PACK(size, alloc) ((size) | (alloc))

/* Read and write a word at address p */
#define GET(p)       (*(unsigned int *)(p))
#define PUT(p, val) (*(unsigned int *)(p) = (val))

/* Read the size and allocated fields from address p */
#define GET_SIZE(p) (GET(p) & ~0x7)
#define GET_ALLOC(p) (GET(p) & 0x1)

/* Given block ptr bp, compute address of its header and footer */
#define HDRP(bp)       ((char *)(bp) - WSIZE)
#define FTRP(bp)       ((char *)(bp) + GET_SIZE(HDRP(bp)) - DSIZE)

/* Given block ptr bp, compute address of next and previous blocks */
#define NEXT_BLKP(bp) ((char *)(bp) + GET_SIZE(((char *)(bp) - WSIZE)))
#define PREV_BLKP(bp) ((char *)(bp) - GET_SIZE(((char *)(bp) - DSIZE)))
/* @END */

/* @ADDED A3: heap_listp 선언. 책은 Fig 9.42 도해에만 'static char *heap_listp' 로 그려 두고 코드에는 없다. 제거 시: 'heap_listp' undeclared */
static char *heap_listp;
/* @END */

/* @ADDED A4: extend_heap 의 prototype. mm_init 이 정의보다 먼저 호출한다. 제거 시: implicit declaration of 'extend_heap' */
static void *extend_heap(size_t words);
/* @END */

/* @ADDED A5: coalesce 의 prototype. extend_heap 이 정의보다 먼저 호출한다. 제거 시: implicit declaration of 'coalesce' */
static void *coalesce(void *bp);
/* @END */

/* @ADDED A6: find_fit 의 prototype. mm_malloc 이 정의보다 먼저 호출한다. 제거 시: implicit declaration of 'find_fit' */
static void *find_fit(size_t asize);
/* @END */

/* @ADDED A7: place 의 prototype. mm_malloc 이 정의보다 먼저 호출한다. 제거 시: implicit declaration of 'place' */
static void place(void *bp, size_t asize);
/* @END */

/* @BOOK Fig 9.44, p.894 */
int mm_init(void)
{
    /* Create the initial empty heap */
    if ((heap_listp = mem_sbrk(4*WSIZE)) == (void *)-1)
        return -1;
    PUT(heap_listp, 0);                          /* Alignment padding */
    PUT(heap_listp + (1*WSIZE), PACK(DSIZE, 1)); /* Prologue header */
    PUT(heap_listp + (2*WSIZE), PACK(DSIZE, 1)); /* Prologue footer */
    PUT(heap_listp + (3*WSIZE), PACK(0, 1));     /* Epilogue header */
    heap_listp += (2*WSIZE);

    /* Extend the empty heap with a free block of CHUNKSIZE bytes */
    if (extend_heap(CHUNKSIZE/WSIZE) == NULL)
        return -1;
    return 0;
}
/* @END */

/* @BOOK Fig 9.45, p.894 */
static void *extend_heap(size_t words)
{
    char *bp;
    size_t size;

    /* Allocate an even number of words to maintain alignment */
    size = (words % 2) ? (words+1) * WSIZE : words * WSIZE;
    if ((long)(bp = mem_sbrk(size)) == -1)
        return NULL;

    /* Initialize free block header/footer and the epilogue header */
    PUT(HDRP(bp), PACK(size, 0));         /* Free block header */
    PUT(FTRP(bp), PACK(size, 0));         /* Free block footer */
    PUT(HDRP(NEXT_BLKP(bp)), PACK(0, 1)); /* New epilogue header */

    /* Coalesce if the previous block was free */
    return coalesce(bp);
}
/* @END */

/* @BOOK Fig 9.46, p.896 */
void mm_free(void *bp)
{
    size_t size = GET_SIZE(HDRP(bp));

    PUT(HDRP(bp), PACK(size, 0));
    PUT(FTRP(bp), PACK(size, 0));
    coalesce(bp);
}

static void *coalesce(void *bp)
{
    size_t prev_alloc = GET_ALLOC(FTRP(PREV_BLKP(bp)));
    size_t next_alloc = GET_ALLOC(HDRP(NEXT_BLKP(bp)));
    size_t size = GET_SIZE(HDRP(bp));

    if (prev_alloc && next_alloc) {            /* Case 1 */
        return bp;
    }

    else if (prev_alloc && !next_alloc) {      /* Case 2 */
        size += GET_SIZE(HDRP(NEXT_BLKP(bp)));
        PUT(HDRP(bp), PACK(size, 0));
        PUT(FTRP(bp), PACK(size,0));
    }

    else if (!prev_alloc && next_alloc) {      /* Case 3 */
        size += GET_SIZE(HDRP(PREV_BLKP(bp)));
        PUT(FTRP(bp), PACK(size, 0));
        PUT(HDRP(PREV_BLKP(bp)), PACK(size, 0));
        bp = PREV_BLKP(bp);
    }

    else {                                     /* Case 4 */
        size += GET_SIZE(HDRP(PREV_BLKP(bp))) +
            GET_SIZE(FTRP(NEXT_BLKP(bp)));
        PUT(HDRP(PREV_BLKP(bp)), PACK(size, 0));
        PUT(FTRP(NEXT_BLKP(bp)), PACK(size, 0));
        bp = PREV_BLKP(bp);
    }
    return bp;
}
/* @END */

/* @BOOK Fig 9.47, p.897 */
void *mm_malloc(size_t size)
{
    size_t asize;      /* Adjusted block size */
    size_t extendsize; /* Amount to extend heap if no fit */
    char *bp;

    /* Ignore spurious requests */
    if (size == 0)
        return NULL;

    /* Adjust block size to include overhead and alignment reqs. */
    if (size <= DSIZE)
        asize = 2*DSIZE;
    else
        asize = DSIZE * ((size + (DSIZE) + (DSIZE-1)) / DSIZE);

    /* Search the free list for a fit */
    if ((bp = find_fit(asize)) != NULL) {
        place(bp, asize);
        return bp;
    }

    /* No fit found. Get more memory and place the block */
    extendsize = MAX(asize,CHUNKSIZE);
    if ((bp = extend_heap(extendsize/WSIZE)) == NULL)
        return NULL;
    place(bp, asize);
    return bp;
}
/* @END */

/* @BOOK-FIX Sol 9.8, p.920 | drop: #endif */
static void *find_fit(size_t asize)
{
    /* First-fit search */
    void *bp;

    for (bp = heap_listp; GET_SIZE(HDRP(bp)) > 0; bp = NEXT_BLKP(bp)) {
        if (!GET_ALLOC(HDRP(bp)) && (asize <= GET_SIZE(HDRP(bp)))) {
            return bp;
        }
    }
    return NULL; /* No fit */
}
/* @END */

/* @BOOK Sol 9.9, p.920 */
static void place(void *bp, size_t asize)
{
    size_t csize = GET_SIZE(HDRP(bp));

    if ((csize - asize) >= (2*DSIZE)) {
        PUT(HDRP(bp), PACK(asize, 1));
        PUT(FTRP(bp), PACK(asize, 1));
        bp = NEXT_BLKP(bp);
        PUT(HDRP(bp), PACK(csize-asize, 0));
        PUT(FTRP(bp), PACK(csize-asize, 0));
    }
    else {
        PUT(HDRP(bp), PACK(csize, 1));
        PUT(FTRP(bp), PACK(csize, 1));
    }
}
/* @END */

/* @ADDED A8: mm_realloc. 책에 없고 mdriver 가 호출한다. 제거 시: undefined reference to 'mm_realloc' */
/*
 * 책의 블록 구조(payload 바로 앞이 header)에 맞춘 가장 단순한 구현이다.
 * starter 의 mm_realloc 은 payload 앞 8바이트를 길이(size_t)로 읽는데, 이 구조에서
 * 그 자리는 [앞 블록 footer][이 블록 header] 라서 길이가 아니다. 그래도 13개 trace 를
 * 통과하지만 우연이다(리틀엔디언에서 값이 항상 2^32 이상이라 min() 이 새 크기를 고른다).
 * 그래서 복사 길이를 header 에서 직접 계산한다: 블록 크기 - header - footer.
 */
void *mm_realloc(void *ptr, size_t size)
{
    void *newptr;
    size_t copySize;

    newptr = mm_malloc(size);
    if (newptr == NULL)
        return NULL;
    copySize = GET_SIZE(HDRP(ptr)) - DSIZE;
    if (size < copySize)
        copySize = size;
    memcpy(newptr, ptr, copySize);
    mm_free(ptr);
    return newptr;
}
/* @END */
