.messages[]
    | select(.role == "tool_result")
    | (.text // "") as $text
    | (($text | capture("(?m)^(?:Process exited with code|Exit code) (?<code>[0-9]+)$")? | .code | tonumber) // null) as $exit_code
    | (.tool_result_exit_code // $exit_code) as $normalized_exit_code
    | ((.tool_result_status // "") | tostring) as $status
    | (
        .tool_result_error == true
        or ($status | test("(?i)^(error|errored|failed|failure|cancelled|canceled)$"))
        or ($normalized_exit_code != null and $normalized_exit_code != 0)
      ) as $confirmed_failure
    | ($text | test("(?im)(^|\\n)(traceback|error:|fatal:|panic:|exception:|permission denied|command not found|no such file|zsh:|bash:|sh:)")) as $strong_runtime_signal
    | ($text | test("(?im)(^|\\n)(error\\[[A-Za-z0-9_-]+\\]:|compilation failed|could not compile)")) as $compiler_signal
    | ($text | test("(?i)(sandbox denied|failed in sandbox)")) as $sandbox_signal
    | ($text | test("(?m)^\\s*(ERROR|FATAL|PANIC)\\b")) as $log_error_signal
    | ($text | test("(?im)(^|\\n)\\s*usage:")) as $usage_signal
    | ($text | test("(?im)(illegal option|unknown option|unrecognized option|unrecognized argument|invalid option|invalid choice|invalid argument|no such option|missing required|too few arguments|unexpected argument)")) as $arg_failure_signal
    | ($text | test("(?m)^(?:[0-9]+\\t)?(diff --git|@@ |--- a/|\\+\\+\\+ b/)")) as $looks_like_diff
    | (
        $confirmed_failure == false
        and ($looks_like_diff == false)
        and (
          $strong_runtime_signal
          or $compiler_signal
          or $sandbox_signal
          or $log_error_signal
          or ($usage_signal and $arg_failure_signal)
        )
      ) as $review_candidate
    | select($confirmed_failure or $review_candidate)
    | {
        index,
        tool_call_id,
        signal: (if $confirmed_failure then "confirmed_failure" else "review_candidate" end),
        confidence: (if $confirmed_failure then "high" else "low" end),
        exit_code: $normalized_exit_code,
        tool_result_status,
        tool_result_error,
        text: ($text | .[0:500])
      }
