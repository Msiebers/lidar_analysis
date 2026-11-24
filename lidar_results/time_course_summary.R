#!/usr/bin/env Rscript
# Interactive within-experiment LiDAR time course.
# Input: curated within_day/results.csv, read-only.
# Output: time_course/index.html, results.csv (all dates), changes.csv (paired deltas).
# v2.1 fix: properly distinguish nonexistent files from symlinks on first run.
# Does not read/write/copy or modify groundtruth/ or original LiDAR data.

fail <- function(message) stop(message, call. = FALSE)
usage <- function() {
  cat(paste(
    'Usage: Rscript time_course_summary.R EXPERIMENT_DIR [--name ANALYSIS_NAME]',
    '',
    '  Reads <raw_mirror>/results/<name>/within_day/results.csv',
    '  Writes <raw_mirror>/results/<name>/time_course/index.html',
    '       <raw_mirror>/results/<name>/time_course/results.csv (all date measurements)',
    '       <raw_mirror>/results/<name>/time_course/changes.csv (paired date-to-date changes)',
    '  Default --name is the experiment folder name.',
    '', sep='\n'))
}
args <- commandArgs(trailingOnly=TRUE)
if (!length(args) || '--help' %in% args || '-h' %in% args) {
  usage(); quit(save='no', status=0)
}
if (startsWith(args[[1]], '--')) fail('First argument must be the experiment folder')
experiment <- normalizePath(path.expand(args[[1]]), mustWork=FALSE)
if (!dir.exists(experiment)) fail(paste('Experiment folder not found:', experiment))
experiment <- normalizePath(experiment, winslash='/', mustWork=TRUE)
name <- basename(experiment)
if (length(args)>1L) {
  if (length(args)!=3L || args[[2]]!='--name') fail('Only optional argument is --name ANALYSIS_NAME')
  name <- args[[3]]
}
if (!grepl('^[A-Za-z0-9][A-Za-z0-9_.-]*$', name) || name %in% c('.', '..'))
  fail('Analysis name must contain only letters, numbers, underscores, hyphens, and dots')
analysis_root <- file.path(dirname(experiment), 'results', name)
input <- file.path(analysis_root, 'within_day', 'results.csv')
output <- file.path(analysis_root, 'time_course')
if (!file.exists(input)) fail(paste('Cleaned within-day results not found:', input,
  '\nRun: with_day', basename(experiment), name))

# Guard paths, including symlinks. Never write to a source experiment, within_day, or groundtruth.
canonical <- function(p) {
  p <- normalizePath(path.expand(p), winslash='/', mustWork=FALSE)
  if (file.exists(p) || dir.exists(p))
    return(normalizePath(p, winslash='/', mustWork=TRUE))
  suffix <- character(); parent <- p
  while (!dir.exists(parent)) {
    n <- dirname(parent)
    if (identical(n,parent)) fail(paste('Cannot resolve',p))
    suffix <- c(basename(parent),suffix); parent <- n
  }
  do.call(file.path,as.list(c(normalizePath(parent,winslash='/',mustWork=TRUE),suffix)))
}
contains <- function(parent, candidate) identical(parent,candidate) || startsWith(candidate,paste0(parent,'/'))
resolved_output <- canonical(output)
protected <- c(experiment, file.path(analysis_root,'within_day'),file.path(analysis_root,'groundtruth'))
if (any(vapply(protected,function(x) contains(canonical(x),resolved_output) || contains(resolved_output,canonical(x)),logical(1))))
  fail('Refusing to write time_course inside or over the experiment, within_day, or groundtruth')
# Sys.readlink() may return NA for a path that does not exist yet.
# Treat only an actual, resolved symlink as a link; never follow a link when writing.
is_link <- function(path) {
  target <- Sys.readlink(path)
  length(target) == 1L && !is.na(target) && nzchar(target)
}
for (dest in file.path(output,c('index.html','results.csv','changes.csv'))) {
  if (is_link(dest)) fail(paste('Refusing to overwrite a symlink:',dest))
}

x <- tryCatch(utils::read.csv(input,stringsAsFactors=FALSE,check.names=FALSE,
  na.strings=c('', 'NA', 'N/A', 'NaN', 'null'),fileEncoding='UTF-8-BOM'),
  error=function(e) fail(paste('Could not read within_day/results.csv:', conditionMessage(e))))
if (!nrow(x)) fail('within_day/results.csv has no observations')
required <- c('date','row')
if (!all(required %in% names(x))) fail(paste('Input must include columns:',paste(required,collapse=', ')))
kind <- intersect(c('plant','plot'),names(x))
if (length(kind)!=1L) fail('Input needs exactly one position column named plant OR plot')
kind <- kind[[1]]
x$date <- gsub('_','-',trimws(as.character(x$date)),fixed=TRUE)
x$day <- suppressWarnings(as.Date(x$date,format='%Y-%m-%d'))
if (anyNA(x$day) || any(format(x$day,'%Y-%m-%d')!=x$date)) fail('Invalid dates in within_day/results.csv')
all_dates <- sort(unique(x$date))
if (length(all_dates)<2L) fail('Time course needs at least two measurement dates')
if (length(unique(format(x$day,'%Y')))>1L)
  fail('Time-course v1 supports a single calendar year per analysis. Multi-year comparisons will be added later.')
x$row <- suppressWarnings(as.integer(as.character(x$row)))
x[[kind]] <- suppressWarnings(as.integer(as.character(x[[kind]])))
if (anyNA(x$row) || anyNA(x[[kind]]) || any(x$row<1 | x[[kind]]<1))
  fail('row and plant/plot columns must contain positive whole numbers')
if (!'experiment' %in% names(x)) x$experiment <- basename(experiment)
if (!'id' %in% names(x)) x$id <- NA_character_
x$id <- trimws(as.character(x$id))
x$id[is.na(x$id) | !nzchar(x$id)] <- NA_character_
x$position_key <- paste(x$row,x[[kind]],sep=':')
if (anyDuplicated(paste(x$date,x$position_key,sep='|'))) {
  example <- which(duplicated(paste(x$date,x$position_key,sep='|')))[[1]]
  fail(sprintf('Duplicate result for %s, row %s %s %s. Resolve duplicates before time-course analysis.',
    x$date[[example]], x$row[[example]],kind,x[[kind]][[example]]))
}
# Do not silently assign a given physical position to different breeder IDs over time.
for (g in split(x$id,x$position_key)) {
  ids <- unique(stats::na.omit(g))
  if (length(ids)>1L) fail(paste('Breeder IDs change across dates at one field position:',paste(ids,collapse=' vs ')))
}
# Only intended biological columns, not identifiers/dimensions or QC numeric metadata.
known_traits <- c('height_m','lai_even','lai_uneven','fad_app_m2_m3','z_pai_m2_m2',
  'point_density_m2','stacked_hull_volume_m3','max_spread_m','spread_at_50_m',
  'canopy_volume_2p5d_m3','canopy_volume_2p5d_m3_m2','voxel_count')
traits <- intersect(known_traits,names(x))
for (trait in traits) x[[trait]] <- suppressWarnings(as.numeric(as.character(x[[trait]])))
traits <- traits[vapply(traits,function(t) any(is.finite(x[[t]])),logical(1))]
if (!length(traits)) fail('No numeric LiDAR traits recognized in within_day/results.csv')
x$doy <- as.integer(format(x$day,'%j'))
x <- x[order(x$day,x$row,x[[kind]]),,drop=FALSE]
rownames(x) <- NULL

# A single researcher-facing table with ALL selected original LiDAR measurements,
# for every date. One row per position per observation date (long/tidy format).
# day_of_year and measurement_number make downstream analysis straightforward.
# Never collapse plants into a per-date mean or drop traits not shown in HTML.
merged <- x
merged$day_of_year <- merged$doy
merged$measurement_number <- match(merged$date, all_dates)
merged$day <- NULL
merged$doy <- NULL
merged$position_key <- NULL
front <- c('experiment','date','day_of_year','measurement_number','row',kind)
merged <- merged[,c(front, setdiff(names(merged),front)),drop=FALSE]

# Derived paired consecutive-DATE trait changes, delivered in long/tidy form.
# Never join different individuals on row or position alone.
changes <- list(); k <- 0L
for (j in seq_len(length(all_dates)-1L)) {
  a <- x[x$date==all_dates[[j]],,drop=FALSE]
  b <- x[x$date==all_dates[[j+1L]],,drop=FALSE]
  matched <- match(a$position_key,b$position_key)
  ok <- !is.na(matched)
  if (!any(ok)) next
  left <- a[ok,,drop=FALSE]; right <- b[matched[ok],,drop=FALSE]
  elapsed <- as.integer(right$day - left$day)
  if (any(elapsed<=0L)) fail('Measurement dates are not in strictly increasing order')
  for (trait in traits) {
    start <- left[[trait]]; end <- right[[trait]]
    valid <- is.finite(start) & is.finite(end)
    if (!any(valid)) next
    begin <- start[valid]; finish <- end[valid]
    # Near-zero threshold is 1% of this interval's median |baseline| (minimum 1e-8).
    scale <- stats::median(abs(begin),na.rm=TRUE)
    threshold <- max(1e-8, 0.01*scale)
    near <- abs(begin)<=threshold
    pct <- rep(NA_real_,length(begin))
    pct[!near] <- 100*(finish[!near]-begin[!near])/begin[!near]
    ids <- left$id[valid]
    missing_ids <- is.na(ids) & !is.na(right$id[valid])
    ids[missing_ids] <- right$id[valid][missing_ids]
    k <- k+1L
    piece <- data.frame(experiment=left$experiment[valid], row=left$row[valid],
      date_start=left$date[valid],date_end=right$date[valid],
      doy_start=left$doy[valid],doy_end=right$doy[valid],
      days_elapsed=elapsed[valid], id=ids,
      trait=rep(trait,length(begin)), value_start=begin,value_end=finish,
      absolute_change=finish-begin,daily_change=(finish-begin)/elapsed[valid],
      percent_change=pct,
      percent_flag=ifelse(near,'baseline_near_zero',''),
      stringsAsFactors=FALSE,check.names=FALSE)
    piece[[kind]] <- left[[kind]][valid]
    piece <- piece[,c('experiment','row',kind,'id','date_start','date_end',
      'doy_start','doy_end','days_elapsed','trait','value_start','value_end',
      'absolute_change','daily_change','percent_change','percent_flag'),drop=FALSE]
    changes[[k]] <- piece
  }
}
if (length(changes)) {
  derived <- do.call(rbind,changes)
  derived <- derived[order(derived$date_start,derived$row,derived[[kind]],derived$trait),,drop=FALSE]
  rownames(derived) <- NULL
} else {
  derived <- data.frame(experiment=character(),row=integer(),id=character(),
    date_start=character(),date_end=character(),doy_start=integer(),doy_end=integer(),
    days_elapsed=integer(),trait=character(),value_start=numeric(),value_end=numeric(),
    absolute_change=numeric(),daily_change=numeric(),percent_change=numeric(),
    percent_flag=character(),stringsAsFactors=FALSE)
  derived[[kind]] <- integer()
  derived <- derived[,c('experiment','row',kind,'id','date_start','date_end',
      'doy_start','doy_end','days_elapsed','trait','value_start','value_end',
      'absolute_change','daily_change','percent_change','percent_flag')]
}

# JSON serializer in base R. Escape '<' for safely embedded inline script data.
json_string <- function(v) {
  # encodeString handles quotes, backslashes, control characters and Unicode.
  s <- encodeString(enc2utf8(as.character(v)), quote='"')
  # Literal < can terminate an inline <script> payload when followed by /script>.
  if (grepl('<',s,fixed=TRUE))
    s <- paste(strsplit(s,'<',fixed=TRUE)[[1]], collapse=paste0(intToUtf8(92),'u003c'))
  s
}
json_value <- function(v) {
  if (is.data.frame(v)) {
    if (!nrow(v)) return('[]')
    return(paste0('[',paste(vapply(seq_len(nrow(v)),function(i)
      json_value(as.list(v[i,,drop=FALSE])),character(1)),collapse=','),']'))
  }
  if (is.list(v)) {
    if (!length(v)) return(if (is.null(names(v))) '[]' else '{}')
    if (!is.null(names(v))) {
      fields <- paste0(vapply(names(v),json_string,character(1)),':',
                       vapply(v,json_value,character(1)))
      return(paste0('{',paste(fields,collapse=','),'}'))
    }
    return(paste0('[',paste(vapply(v,json_value,character(1)),collapse=','),']'))
  }
  if (length(v)!=1L) return(paste0('[',paste(vapply(as.list(v),json_value,character(1)),collapse=','),']'))
  if (is.na(v) || (is.numeric(v) && !is.finite(v))) return('null')
  if (is.logical(v)) return(if (isTRUE(v)) 'true' else 'false')
  if (is.numeric(v) || is.integer(v)) return(format(v,scientific=FALSE,trim=TRUE,digits=16))
  json_string(v)
}

script_arg <- grep('^--file=',commandArgs(),value=TRUE)
if (!length(script_arg)) fail('Cannot find script path to locate HTML template')
script_path <- normalizePath(sub('^--file=','',script_arg[[1]]),mustWork=TRUE)
template_path <- file.path(dirname(script_path),'time_course_template.html')
if (!file.exists(template_path)) fail(paste('HTML template not found:',template_path))
template <- paste(readLines(template_path,encoding='UTF-8',warn=FALSE),collapse='\n')
placeholder <- '__EMBEDDED_TIME_COURSE__'
parts <- strsplit(template,placeholder,fixed=TRUE)[[1]]
if (length(parts)!=2L) fail('Template must contain exactly one __EMBEDDED_TIME_COURSE__ placeholder')
# Include the SAME full merged table in the offline HTML so users can export it
# even if only index.html is shared. R.records is no longer trait-subsetted.
records <- merged
payload <- list(analysis=name,experiment=basename(experiment),kind=kind,
  dates=all_dates,traits=traits,columns=names(merged),records=records,change_rows=nrow(derived))
html <- paste0(parts[[1]],json_value(payload),parts[[2]])
# No cleanup, archive, or recursive writes: only update our own three generated files.
dir.create(output,recursive=TRUE,showWarnings=FALSE)
for (dest in file.path(output,c('index.html','results.csv','changes.csv'))) {
  if (is_link(dest)) fail(paste('Refusing to overwrite a symlink:',dest))
}
utils::write.csv(merged,file.path(output,'results.csv'),row.names=FALSE,na='')
utils::write.csv(derived,file.path(output,'changes.csv'),row.names=FALSE,na='')
writeLines(html,file.path(output,'index.html'),useBytes=TRUE)
cat(sprintf('Time course: %s\nInput (read only): %s\nDates: %s\nTraits: %d\nCombined measurement rows: %d\nPaired change rows: %d\nOpen: %s\nCombined data: %s\nChanges: %s\n',
  name,input,paste(all_dates,collapse=', '),length(traits),nrow(merged),nrow(derived),
  file.path(output,'index.html'),file.path(output,'results.csv'),file.path(output,'changes.csv')))
cat('No groundtruth files, source experiment results, or within_day files were modified.\n')
