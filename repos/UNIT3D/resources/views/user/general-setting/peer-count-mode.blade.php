@if (config('dualstack.enabled'))
    <p class="form__group">
        <select id="peer_count_mode" class="form__select" name="peer_count_mode" required>
            @foreach (['sum', 'ipv4', 'ipv6', 'auto'] as $mode)
                <option class="form__option" value="{{ $mode }}" @selected(old('peer_count_mode', $user->peer_count_mode ?? 'sum') === $mode)>
                    {{ __('dualstack.peer-count-' . $mode) }}
                </option>
            @endforeach
        </select>
        <label class="form__label form__label--floating" for="peer_count_mode">{{ __('dualstack.peer-count-mode') }}</label>
        <small>{{ __('dualstack.peer-count-help') }}</small>
    </p>
@endif
