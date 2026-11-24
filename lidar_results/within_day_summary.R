#!/usr/bin/env Rscript
# Within-day interactive LiDAR report. Requires base R only.
# Original date-folder results.csv files are read-only.
# Output: within_day/index.html (full QC data embedded) plus
#         within_day/results.csv (curated researcher-facing measurements).


fail <- function(x) stop(x, call. = FALSE)
usage <- function() cat(paste(
  "Usage: Rscript within_day_summary.R EXPERIMENT_DIR --name ANALYSIS_NAME [options]",
  "", "Options:",
  "  --name NAME         Named analysis in raw_mirror/results/ (defaults to experiment name)",
  "  --date YYYY_MM_DD   Restrict LiDAR measurements (may be repeated or comma separated)",
  "  --traits A,B,C      Restrict selectable LiDAR traits to these numeric columns",
  "  --output DIR        Override within_day output directory",
  "  --groundtruth DIR   Override groundtruth directory (default: <analysis>/groundtruth)",
  "  --gt-date DATE      Assign an explicit date to an otherwise undated groundtruth file",
  "                      (only allowed if exactly one CSV is present and it has no dates)",
  "  --no-archive       Keep previous generated HTML/CSVs/assets in within_day/",
  "  --help              Print this help", sep="\n"))

parse_args <- function(args) {
  if (!length(args) || "--help" %in% args || "-h" %in% args) {
    usage(); quit(save="no", status=0)
  }
  if (startsWith(args[[1]], "--")) fail("The first argument must be the source experiment folder")
  a <- list(experiment=args[[1]], name=NULL, dates=character(), traits=character(),
            output=NULL, groundtruth=NULL, gt_date=NULL, archive=TRUE)
  i <- 2L
  while (i <= length(args)) {
    k <- args[[i]]
    if (k == "--no-archive") { a$archive <- FALSE; i <- i + 1L; next }
    if (k == "--archive-legacy") { a$archive <- TRUE; i <- i + 1L; next } # older flag
    if (!(k %in% c("--name", "--date", "--traits", "--output", "--groundtruth", "--gt-date")))
      fail(paste("Unknown argument:", k))
    if (i == length(args)) fail(paste("Missing argument after", k))
    v <- args[[i+1L]]
    if (k == "--name") a$name <- v
    if (k == "--date") a$dates <- c(a$dates, trimws(strsplit(v, ",", fixed=TRUE)[[1]]))
    if (k == "--traits") a$traits <- c(a$traits, trimws(strsplit(v, ",", fixed=TRUE)[[1]]))
    if (k == "--output") a$output <- v
    if (k == "--groundtruth") a$groundtruth <- v
    if (k == "--gt-date") a$gt_date <- v
    i <- i + 2L
  }
  a$dates <- unique(gsub("-", "_", a$dates, fixed=TRUE))
  a$traits <- unique(a$traits[nzchar(a$traits)])
  a
}

read_csv <- function(path) {
  tryCatch({
    x <- utils::read.csv(path, check.names=FALSE, stringsAsFactors=FALSE,
       na.strings=c("", "NA", "N/A", "null", "NULL", "NaN"), fileEncoding="UTF-8-BOM")
    names(x) <- sub("^\ufeff", "", names(x))
    x
  }, error=function(e) fail(sprintf("Cannot read %s: %s", path, conditionMessage(e))))
}
find_col <- function(df, options) {
  headers <- tolower(trimws(names(df)))
  for (option in options) {
    hits <- which(headers == tolower(option))
    if (length(hits) == 1L) return(names(df)[[hits]])
    if (length(hits) > 1L) fail(paste("Ambiguous column", option))
  }
  NULL
}
valid_name <- function(x) {
  if (is.null(x)) fail("Analysis name is missing")
  if (!grepl("^[A-Za-z0-9][A-Za-z0-9_.-]*$", x) || x %in% c(".", ".."))
    fail("Analysis name must contain only letters, numbers, underscores, dots, or hyphens")
  x
}
parse_date <- function(x) {
  x <- trimws(as.character(x))
  x[is.na(x)] <- ""
  x <- gsub("_", "-", x, fixed=TRUE)
  x <- sub("^([0-9]{4})([0-9]{2})([0-9]{2})$", "\\1-\\2-\\3", x)
  x <- sub("^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})$", "\\3-\\1-\\2", x)
  # as.Date() may be lenient about impossible dates: enforce round-trip.
  normalized <- vapply(x, function(s) {
    if (!grepl("^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}$", s)) return(NA_character_)
    p <- strsplit(s, "-", fixed=TRUE)[[1]]
    sprintf("%04d-%02d-%02d", as.integer(p[[1]]), as.integer(p[[2]]), as.integer(p[[3]]))
  }, character(1))
  d <- suppressWarnings(as.Date(normalized, format="%Y-%m-%d"))
  good <- !is.na(d) & !is.na(normalized) & format(d, "%Y-%m-%d") == normalized
  ifelse(good, as.character(d), NA_character_)
}
filename_date <- function(path) {
  s <- basename(path)
  matches <- regmatches(s, gregexpr("(?:19|20)[0-9]{2}[-_]?[0-9]{2}[-_]?[0-9]{2}", s, perl=TRUE))[[1]]
  if (!length(matches) || identical(matches, character(0))) return(NA_character_)
  vals <- unique(na.omit(parse_date(matches)))
  if (length(vals) > 1L) fail(paste("Multiple dates in groundtruth filename:", s))
  if (!length(vals)) return(NA_character_)
  vals[[1]]
}
json_string <- function(x) {
  # Escape JS-sensitive characters in inline JSON (including </script> attacks).
  x <- enc2utf8(as.character(x))
  x <- gsub("\\\\", "\\\\\\\\", x)
  x <- gsub('"', '\\\\"', x, fixed=TRUE)
  x <- gsub("\r", "\\\\r", x, fixed=TRUE)
  x <- gsub("\n", "\\\\n", x, fixed=TRUE)
  x <- gsub("\t", "\\\\t", x, fixed=TRUE)
  x <- gsub("<", "\\\\u003c", x, fixed=TRUE)
  paste0('"', x, '"')
}
json_value <- function(x) {
  if (is.data.frame(x)) {
    if (nrow(x) == 0L) return("[]")
    rows <- lapply(seq_len(nrow(x)), function(i) as.list(x[i,,drop=FALSE]))
    return(paste0("[", paste(vapply(rows, json_value, character(1)), collapse=","), "]"))
  }
  if (is.list(x)) {
    if (!length(x)) return(if (is.null(names(x))) "[]" else "{}")
    if (!is.null(names(x))) {
      fields <- paste0(vapply(names(x), json_string, character(1)), ":",
                       vapply(x, json_value, character(1)))
      return(paste0("{", paste(fields, collapse=","), "}"))
    }
    return(paste0("[", paste(vapply(x, json_value, character(1)), collapse=","), "]"))
  }
  if (length(x) != 1L) return(paste0("[", paste(vapply(as.list(x), json_value, character(1)), collapse=","), "]"))
  if (is.na(x) || (is.numeric(x) && !is.finite(x))) return("null")
  if (is.logical(x)) return(if (isTRUE(x)) "true" else "false")
  if (is.numeric(x) || is.integer(x)) return(format(x, scientific=FALSE, trim=TRUE, digits=16))
  json_string(x)
}

selected_traits <- function(df, names_requested) {
  numeric_cols <- names(df)[vapply(df, is.numeric, logical(1))]
  if (length(names_requested)) {
    found <- vapply(names_requested, function(c) {
      n <- find_col(df, c)
      if (is.null(n) || !(n %in% numeric_cols)) fail(paste("Nonexistent or nonnumeric LiDAR trait:", c))
      n
    }, character(1))
    return(unique(found))
  }
  available <- c("height_m", "lai_even", "lai_uneven", "fad_app_m2_m3", "z_pai_m2_m2",
     "point_density_m2", "stacked_hull_volume_m3", "max_spread_m", "spread_at_50_m",
     "canopy_volume_2p5d_m3", "canopy_volume_2p5d_m3_m2", "voxel_count")
  available[available %in% numeric_cols]
}

discover_results <- function(root, requested) {
  dirs <- list.dirs(root, recursive=FALSE, full.names=TRUE)
  ds <- parse_date(basename(dirs))
  good <- !is.na(ds) & file.exists(file.path(dirs, "results.csv"))
  dirs <- dirs[good]; ds <- ds[good]
  if (!length(ds)) fail(paste("No measurement-date folders with results.csv under", root))
  if (length(requested)) {
    requested <- gsub("_", "-", requested, fixed=TRUE)
    absent <- setdiff(requested, ds)
    if (length(absent)) fail(paste("Unknown LiDAR date(s):", paste(absent, collapse=", ")))
    keep <- ds %in% requested; dirs <- dirs[keep]; ds <- ds[keep]
  }
  o <- order(ds)
  data.frame(date=ds[o], path=file.path(dirs[o], "results.csv"), stringsAsFactors=FALSE)
}

read_key <- function(experiment) {
  options <- file.path(c(experiment, file.path(experiment,"results"),
                   file.path(experiment,"metadata")), "plot_key.csv")
  p <- options[file.exists(options)]
  if (length(p) > 1L) fail(paste("Multiple plot_key.csv files:", paste(p,collapse=", ")))
  if (!length(p)) return(list(path="", data=data.frame()))
  key <- read_csv(p[[1]])
  if (is.null(find_col(key,"target_id")) || is.null(find_col(key,"breeder_id")))
    fail("plot_key.csv must contain target_id and breeder_id")
  key$target_id <- trimws(as.character(key[[find_col(key,"target_id")]]))
  key$breeder_id <- trimws(as.character(key[[find_col(key,"breeder_id")]]))
  if (anyNA(key$target_id) || any(!nzchar(key$target_id)) || anyDuplicated(key$target_id))
    fail("plot_key.csv contains duplicate or empty target IDs")
  if (anyNA(key$breeder_id) || any(!nzchar(key$breeder_id)) || anyDuplicated(key$breeder_id))
    fail("plot_key.csv contains duplicate or empty breeder IDs")
  list(path=p[[1]], data=key)
}

load_groundtruth <- function(folder, date_override=NULL) {
  if (!dir.exists(folder)) return(list())
  paths <- sort(list.files(folder, pattern="\\.csv$", full.names=TRUE, ignore.case=TRUE))
  if (length(paths) > 25L) fail("More than 25 groundtruth CSVs; split into separate analyses")
  out <- vector("list", length(paths))
  for (i in seq_along(paths)) {
    p <- paths[[i]]
    df <- read_csv(p)
    if (!nrow(df)) { warning(paste("Ignoring empty groundtruth CSV:",p)); next }
    dcol <- find_col(df, c("date","measurement_date","collection_date","sample_date","sampled_date"))
    if (!is.null(dcol)) {
      dates <- parse_date(df[[dcol]])
      bad <- !is.na(df[[dcol]]) & is.na(dates)
      if (any(bad)) fail(sprintf("Invalid date values in %s column %s (e.g. row %s)",
                                  basename(p), dcol, which(bad)[[1]]+1L))
      origin <- paste0("column: ", dcol)
      # Rows with no date are kept but marked as undated.
    } else {
      d <- filename_date(p)
      dates <- rep(d, nrow(df))
      origin <- if (is.na(d)) "missing" else "filename"
      if (is.na(d) && !is.null(date_override)) {
        if (length(paths) != 1L) fail("--gt-date works only with one groundtruth CSV")
        d <- parse_date(date_override)
        if (is.na(d)) fail(paste("Invalid --gt-date:", date_override))
        dates <- rep(d, nrow(df)); origin <- "--gt-date"
      }
    }
    df$.groundtruth_date <- dates
    # Row and column values are included for ID matching, not offered as traits.
    exclude <- tolower(c("id","breeder_id","target_id","lidar_id","row","col","column",
                          "range","lidar_row","lidar_position","lidar_plant","lidar_plot",
                          "date","measurement_date","collection_date","sample_date","sampled_date"))
    measures <- names(df)[vapply(df,is.numeric,logical(1)) &
                            !(tolower(names(df)) %in% exclude)]
    out[[i]] <- list(name=tools::file_path_sans_ext(basename(p)),
       filename=basename(p), date_origin=origin, headers=names(df),
       traits=measures, rows=df)
    cat(sprintf("Ground truth: %s (%d rows, %s, %d selectable traits)\n",
      basename(p), nrow(df), origin, length(measures)))
  }
  Filter(Negate(is.null), out)
}

# Export only the experiment identifiers and final measurements researchers
# need. Keep every original processing/QC column in `lidar` for the HTML report.
# In a plant experiment use a `plant` column; for plot experiments use `plot`.
# Never guess which one to use from the old `plot` display column; use target_id.
researcher_results <- function(lidar, experiment_name, has_plot_key) {
  if (!nrow(lidar)) fail("No LiDAR observations found for researcher export")
  target <- trimws(as.character(lidar$target_id))
  pattern <- "^([0-9]+)_(plant|plot)_([0-9]+)$"
  if (anyNA(target) || any(!grepl(pattern, target)))
    fail("Cannot export: one or more target_id values lack a valid row_plant/plot_position")
  type <- sub(pattern, "\\2", target)
  kinds <- unique(type)
  if (length(kinds) != 1L)
    fail(paste("Cannot create one results.csv with both plant and plot observations:",
               paste(kinds, collapse=", ")))

  # Extra/unplanted LiDAR windows are valid QC data, but they are not study
  # positions. The plot key is the authority for inclusion in this delivery.
  keep <- if (has_plot_key) !is.na(lidar$mapped) & lidar$mapped else
          rep(TRUE, nrow(lidar))
  if (!any(keep))
    fail("No targets match plot_key.csv. Check the plot key before exporting results.csv")
  x <- lidar[keep,,drop=FALSE]
  target <- target[keep]
  position_kind <- kinds[[1]]
  record_row <- suppressWarnings(as.integer(sub(pattern, "\\1", target)))
  record_position <- suppressWarnings(as.integer(sub(pattern, "\\3", target)))

  # A new experiment could have different measured trait columns, so include
  # only fields actually present across its date-folder CSVs, in this order.
  measurements <- c(
    "height_m", "lai_even", "lai_uneven", "fad_app_m2_m3", "z_pai_m2_m2",
    "point_density_m2", "plot_length_m", "plot_width_m",
    "stacked_hull_volume_m3", "max_spread_m", "spread_at_50_m",
    "canopy_volume_2p5d_m3", "canopy_volume_2p5d_m3_m2",
    "voxel_count"
  )
  df <- data.frame(experiment=rep(experiment_name,nrow(x)),
                   date=as.character(x$date),
                   row=record_row, stringsAsFactors=FALSE, check.names=FALSE)
  df[[position_kind]] <- record_position
  side_name <- find_col(x, "side")
  df$side <- if (is.null(side_name)) rep(NA_character_, nrow(x)) else
             as.character(x[[side_name]])

  # Prefer the existing experiment label if the source CSV provides one.
  source_exp <- find_col(x, "experiment")
  if (!is.null(source_exp)) {
    values <- as.character(x[[source_exp]])
    ok <- !is.na(values) & nzchar(trimws(values))
    df$experiment[ok] <- values[ok]
  }
  for (field in measurements) {
    actual <- find_col(x, field)
    if (!is.null(actual)) df[[field]] <- x[[actual]]
  }
  for (field in c("breeder_row", "breeder_range")) {
    actual <- find_col(x, field)
    df[[field]] <- if (is.null(actual)) rep(NA_integer_, nrow(x)) else x[[actual]]
  }
  breeder <- find_col(x, "breeder_id")
  df$id <- if (is.null(breeder)) rep(NA_character_, nrow(x)) else
           as.character(x[[breeder]])
  # Sort for research use, rather than preserving the serpentine cart pass order.
  df <- df[order(df$date, df$row, df[[position_kind]], df$side, na.last=TRUE),,drop=FALSE]
  rownames(df) <- NULL
  if (!has_plot_key)
    warning("No plot_key.csv found: exported all measurements, but id and breeder coordinates are unknown")
  omitted <- sum(!keep)
  if (omitted) cat(sprintf("Researcher CSV: excluded %d positions not present in plot_key.csv (retained in HTML QC)\n", omitted))
  cat(sprintf("Researcher CSV: %d rows, %d columns, target type %s\n",
              nrow(df), ncol(df), position_kind))
  df
}

archive_old <- function(folder) {
  if (!dir.exists(folder)) return(invisible())
  old <- list.files(folder, full.names=TRUE, all.files=FALSE, recursive=FALSE)
  old <- old[(basename(old) == "assets" |
              grepl("^(within_day_index|[0-9]{4}_[0-9]{2}_[0-9]{2}.*)\\.(html|csv)$", basename(old)))]
  if (!length(old)) return(invisible())
  target <- file.path(dirname(folder),"_archive","within_day",format(Sys.time(),"%Y%m%d_%H%M%S"))
  dir.create(target, recursive=TRUE, showWarnings=FALSE)
  for (p in old) {
    if (!file.rename(p, file.path(target, basename(p))))
      warning(paste("Could not archive", p))
  }
  cat(sprintf("Archived %s previous generated items to %s\n", length(old), target))
}

# Guard against accidental output into (or over) user-supplied ground-truth data.
# This remains enforced even when --output or --groundtruth paths are overridden.
resolved_path <- function(path) {
  path <- normalizePath(path.expand(path), winslash="/", mustWork=FALSE)
  if (file.exists(path) || dir.exists(path))
    return(normalizePath(path, winslash="/", mustWork=TRUE))
  suffix <- character()
  ancestor <- path
  while (!dir.exists(ancestor)) {
    next_parent <- dirname(ancestor)
    if (identical(next_parent, ancestor)) fail(paste("Cannot resolve path:", path))
    suffix <- c(basename(ancestor), suffix)
    ancestor <- next_parent
  }
  do.call(file.path, as.list(c(normalizePath(ancestor, winslash="/", mustWork=TRUE), suffix)))
}
path_contains <- function(parent, candidate) {
  identical(parent, candidate) || startsWith(candidate, paste0(parent, "/"))
}
protect_groundtruth <- function(report_output, groundtruth_folder) {
  out <- resolved_path(report_output)
  gt <- resolved_path(groundtruth_folder)
  if (path_contains(gt, out) || path_contains(out, gt))
    fail(paste0("Refusing to write report: output path overlaps groundtruth folder.\n",
                "Report output: ", out, "\nGroundtruth: ", gt, "\n",
                "Ground-truth CSVs are read-only. Choose a separate within_day output."))
  invisible(TRUE)
}

opts <- parse_args(commandArgs(trailingOnly=TRUE))
experiment <- normalizePath(path.expand(opts$experiment), mustWork=FALSE)
if (!dir.exists(experiment)) fail(paste("Experiment folder not found:", experiment))
experiment <- normalizePath(experiment, mustWork=TRUE)
name <- valid_name(if (is.null(opts$name)) basename(experiment) else opts$name)
analysis_root <- file.path(dirname(experiment), "results", name)
output <- if (is.null(opts$output)) file.path(analysis_root,"within_day") else path.expand(opts$output)
gt_dir <- if (is.null(opts$groundtruth)) file.path(analysis_root,"groundtruth") else path.expand(opts$groundtruth)
# A rerun may replace within_day/index.html and within_day/results.csv, NEVER groundtruth/.
protect_groundtruth(output, gt_dir)
# The source experiment (including its date folders and source results.csv files) is also read-only.
if (path_contains(resolved_path(experiment), resolved_path(output)) ||
    path_contains(resolved_path(output), resolved_path(experiment)))
  fail("Refusing --output that overlaps the source experiment. Choose a results/ analysis folder.")
# If a generated output file is a symlink, inspect its final destination too.
# This prevents accidentally overwriting an original CSV through a link.
for (generated in c("index.html", "results.csv")) {
  dest <- file.path(output, generated)
  if (file.exists(dest)) {
    resolved_dest <- resolved_path(dest)
    if (path_contains(resolved_path(gt_dir), resolved_dest) ||
        path_contains(resolved_path(experiment), resolved_dest))
      fail(paste("Refusing to overwrite protected source via symlink:", dest))
  }
}
source_files <- discover_results(experiment, opts$dates)
key <- read_key(experiment)
all_results <- lapply(seq_len(nrow(source_files)), function(i) {
  path <- source_files$path[[i]]; date <- source_files$date[[i]]
  df <- read_csv(path)
  if (is.null(find_col(df,"target_id"))) fail(paste("No target_id column in", path))
  df$target_id <- trimws(as.character(df[[find_col(df,"target_id")]]))
  if (anyNA(df$target_id) || any(!nzchar(df$target_id))) fail(paste("Blank target_id in",path))
  valid_target <- grepl("^[0-9]+_(plant|plot)_[0-9]+$", df$target_id)
  if (!all(valid_target)) fail(paste("Unrecognized target ID in", path))
  kinds <- unique(sub("^[0-9]+_(plant|plot)_[0-9]+$", "\\1", df$target_id))
  if (length(kinds) != 1L) fail(paste("Mixed target ID types in", path))
  type_col <- find_col(df, "target_type")
  if (!is.null(type_col) && any(tolower(trimws(df[[type_col]])) != kinds))
    fail(paste("target_type disagrees with target_id in", path))
  df$date <- date
  df$.source_file <- paste0(basename(dirname(path)),"/results.csv")
  if (nrow(key$data)) {
    idx <- match(df$target_id, key$data$target_id)
    df$breeder_id <- key$data$breeder_id[idx]
    df$mapped <- !is.na(idx)
    for (col in c("breeder_row","breeder_range","lidar_row","lidar_position")) {
      if (col %in% names(key$data)) df[[col]] <- key$data[[col]][idx]
    }
  } else {
    df$breeder_id <- NA_character_
    df$mapped <- TRUE # Provisional QC only, not proof of planted position.
  }
  df
})
# Union columns so dates with slightly different processing configurations can coexist.
cols <- unique(unlist(lapply(all_results,names), use.names=FALSE))
all_results <- lapply(all_results,function(x) {
  for (col in setdiff(cols,names(x))) x[[col]] <- NA
  x[,cols,drop=FALSE]
})
lidar <- do.call(rbind,all_results); rownames(lidar) <- NULL
traits <- selected_traits(lidar, opts$traits)
if (!length(traits)) warning("No selectable biological traits found in LiDAR results")
# Ground truth imports are independent of the original breeder plot-ID source file.
groundtruth <- load_groundtruth(gt_dir, opts$gt_date)
dir.create(output, recursive=TRUE, showWarnings=FALSE)
if (opts$archive) archive_old(output)
# Two visible files: a self-contained QC dashboard and a curated delivery CSV.
# Keep full `lidar` including points/scan_name/target_id for HTML QC only.
clean_results <- researcher_results(lidar, basename(experiment), nrow(key$data)>0L)
utils::write.csv(clean_results, file.path(output,"results.csv"), row.names=FALSE, na="")
script_arg <- grep("^--file=",commandArgs(), value=TRUE)
if (!length(script_arg)) fail("Cannot locate within_day_summary.R to load its HTML template")
script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), mustWork=TRUE)
template_path <- file.path(dirname(script_path),"within_day_template.html")
if (!file.exists(template_path)) fail(paste("Required HTML template missing:", template_path))
template <- paste(readLines(template_path,warn=FALSE,encoding="UTF-8"),collapse="\n")
if (!grepl("__EMBEDDED_REPORT_DATA__",template,fixed=TRUE)) fail("HTML template missing placeholder")
payload <- list(analysis=name, experiment=basename(experiment),
  source_experiment=experiment, key_file=key$path,
  groundtruth_dir=gt_dir, dates=source_files$date,
  traits=traits, lidar=lidar, key=key$data, groundtruth=groundtruth)
template_parts <- strsplit(template, "__EMBEDDED_REPORT_DATA__", fixed=TRUE)[[1]]
if (length(template_parts) != 2L) fail("Template must contain exactly one data placeholder")
html <- paste0(template_parts[[1]], json_value(payload), template_parts[[2]])
writeLines(html,file.path(output,"index.html"), useBytes=TRUE)
cat(sprintf("\nAnalysis: %s\nLiDAR dates: %s\nObservations: %d\nGroundtruth CSVs: %d\nPlot key: %s\n",
  name, paste(source_files$date,collapse=", "),nrow(lidar),length(groundtruth),
  if (nzchar(key$path)) key$path else "NOT FOUND — QC provisional"))
cat(sprintf("Open: %s\nCompanion data: %s\n",file.path(output,"index.html"),file.path(output,"results.csv")))
cat("Only generated within_day report files were written; groundtruth/ was read-only and unchanged.\n")
